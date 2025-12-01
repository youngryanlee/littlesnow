import asyncio
import json
from decimal import Decimal
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
import aiohttp
from enum import Enum
from dataclasses import dataclass

from logger.logger import get_logger
from .base_adapter import BaseAdapter
from ..service.ws_connector import WebSocketConnector
from ..service.rest_connector import RESTConnector
from ..core.data_models import MarketData, OrderBook, OrderBookLevel, ExchangeType, MarketType, Trade

logger = get_logger()

class SubscriptionType(Enum):
    """订阅类型枚举"""
    ORDERBOOK = "orderbook"      # 订单簿数据
    TRADES = "trades"           # 交易数据
    PRICES = "prices"           # 价格数据
    COMMENTS = "comments"       # 评论数据

@dataclass
class SubscriptionConfig:
    """订阅配置"""
    endpoint: str
    message_format: Dict
    description: str

class PolymarketAdapter(BaseAdapter):
    """Polymarket WebSocket 适配器 - 毫秒级性能"""
    
    def __init__(self):
        super().__init__("polymarket", ExchangeType.POLYMARKET)

        # 市场数据状态
        self.orderbook_snapshots: Dict[str, OrderBook] = {}
        self.last_sequence_nums: Dict[str, int] = {}
        self.pending_updates: Dict[str, List[dict]] = {}
        
        # 性能监控
        self.message_count = 0
        self.last_message_time = None
        self.performance_stats = {
            "messages_per_second": 0,
            "average_latency": 0,
            "last_update": datetime.now(timezone.utc)
        }

        self.rest_urls = [
            "https://gamma-api.polymarket.com",
            "https://clob.polymarket.com/markets",
        ]

        # 多端点配置
        self.endpoint_configs = {
            SubscriptionType.ORDERBOOK: SubscriptionConfig(
                endpoint="wss://ws-subscriptions-clob.polymarket.com/ws/market",  # 注意路径
                message_format={
                    "assets_ids": [],  # 将在订阅时填充
                    "type": "market"
                },
                description="CLOB 订单簿数据"
            ),
            SubscriptionType.TRADES: SubscriptionConfig(
                endpoint="wss://ws-subscriptions-clob.polymarket.com/ws/market",  # 同一个端点
                message_format={
                    "assets_ids": [],  # 将在订阅时填充
                    "type": "market" 
                },
                description="CLOB 交易数据"
            ),
            # PRICES 和 COMMENTS 保持不变，使用另一个端点
            SubscriptionType.PRICES: SubscriptionConfig(
                endpoint="wss://ws-live-data.polymarket.com",
                message_format={
                    "action": "subscribe",
                    "subscriptions": [
                        {
                            "topic": "crypto_prices",
                            "type": "price_update"
                        }
                    ]
                },
                description="RTDS 加密货币价格"
            ),
            SubscriptionType.COMMENTS: SubscriptionConfig(
                endpoint="wss://ws-live-data.polymarket.com", 
                message_format={
                    "action": "subscribe",
                    "subscriptions": [
                        {
                            "topic": "comments",
                            "type": "new_comment"
                        }
                    ]
                },
                description="RTDS 评论数据"
            )
        }

        # 多个 WebSocket 连接器
        self.connectors: Dict[SubscriptionType, WebSocketConnector] = {}
        self.subscription_status: Dict[SubscriptionType, set] = {}

        # 初始化连接器和状态
        for sub_type in SubscriptionType:
            config = self.endpoint_configs[sub_type]
            self.connectors[sub_type] = WebSocketConnector(
                url=config.endpoint,
                on_message=lambda msg, st=sub_type: self._handle_raw_message(msg),
                on_error=lambda err, st=sub_type: self._handle_connection_error(err, st),
                ping_interval=20,
                timeout=5,
                name=f"polymarket_{sub_type.value}"
            )
            self.subscription_status[sub_type] = set()

        # 扩展状态管理
        self._initialize_all_states()

    def _initialize_all_states(self):
        """初始化所有状态容器"""
        # 订单簿相关状态（从基类继承，确保存在）
        if not hasattr(self, 'orderbook_snapshots'):
            self.orderbook_snapshots = {}
        if not hasattr(self, 'last_sequence_nums'):
            self.last_sequence_nums = {}
        if not hasattr(self, 'pending_updates'):
            self.pending_updates = {}
        
        # 交易相关状态
        self.trade_history = {}  # market_id -> List[Trade]
        
        # 价格相关状态
        self.price_snapshots = {}  # symbol -> PriceSnapshot
        
        # 评论相关状态
        self.comment_streams = {}  # stream_id -> CommentStream
        
        # 性能监控
        self.message_count_by_type = {sub_type: 0 for sub_type in SubscriptionType}
    
    def get_detailed_status(self) -> Dict:
        """获取详细状态信息"""
        base_status = super().get_connection_status()
        
        # 添加状态统计
        state_stats = {
            "orderbook_snapshots": len(self.orderbook_snapshots),
            "trade_history": len(self.trade_history),
            "price_snapshots": len(self.price_snapshots),
            "comment_streams": len(self.comment_streams),
            "message_counts": self.message_count_by_type
        }
        
        # 添加订阅详情
        subscription_details = {}
        for sub_type in SubscriptionType:
            subscription_details[sub_type.value] = {
                "subscribed_markets": list(self.subscription_status[sub_type]),
                "endpoint": self.endpoint_configs[sub_type].endpoint,
                "is_connected": self.connectors[sub_type].is_connected
            }
        
        return {
            **base_status,
            "state_statistics": state_stats,
            "subscription_details": subscription_details
        }        
        
        
    async def connect(self) -> bool:
        """连接所有端点"""
        try:
            logger.info("🔌 Connecting to all WebSocket endpoints...")
            
            tasks = []
            for sub_type, connector in self.connectors.items():
                tasks.append(connector.connect())
            
            results = await asyncio.gather(*tasks, return_exceptions=True)

            # 检查连接结果并启动 Ping
            all_connected = True
            for sub_type, result in zip(self.connectors.keys(), results):
                if isinstance(result, Exception) or not result:
                    logger.error(f"❌ Failed to connect to {sub_type.value}: {result}")
                    all_connected = False
                else:
                    logger.info(f"✅ {sub_type.value} connected successfully")
                    # 启动 Ping 任务
                    asyncio.create_task(self._start_ping(sub_type))
            
            
            if all_connected:
                self.is_connected = True
                self._connection_established = True
                logger.info("✅ All WebSocket endpoints connected successfully")
                
                # 连接成功后立即订阅已注册的交易对
                if any(self.subscription_status.values()):
                    await asyncio.sleep(0.5)  # 给连接一点时间稳定
                    await self._resubscribe_all()
                
                # 启动性能监控
                asyncio.create_task(self._performance_monitor())
                
                return True
            else:
                logger.error("❌ Some WebSocket endpoints failed to connect")
                self.is_connected = False
                self._connection_established = False
                return False
                
        except Exception as e:
            logger.error(f"❌ WebSocket connection failed: {e}")
            self.is_connected = False
            self._connection_established = False
            return False
        
    async def _start_ping(self, subscription_type: SubscriptionType):
        """启动 Ping 机制保持连接"""
        connector = self.connectors[subscription_type]
        while connector.is_connected:
            try:
                await asyncio.sleep(10)  # 每10秒发送一次
                if connector.is_connected:
                    await connector.send_text("PING")
            except Exception as e:
                logger.error(f"Ping 失败: {e}")
                break    

    async def _resubscribe_all(self):
        """重新订阅所有已注册的交易对"""
        for sub_type, symbols in self.subscription_status.items():
            if symbols:
                await self._do_subscribe(list(symbols), sub_type)

    async def disconnect(self):
        """断开所有连接"""
        try:
            logger.info("🔌 Disconnecting from all WebSocket endpoints...")
            
            tasks = []
            for sub_type, connector in self.connectors.items():
                tasks.append(connector.disconnect())
            
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # 记录断开连接结果
            for sub_type, result in zip(self.connectors.keys(), results):
                if isinstance(result, Exception):
                    logger.error(f"❌ Failed to disconnect from {sub_type.value}: {result}")
                else:
                    logger.info(f"✅ {sub_type.value} disconnected successfully")
            
            # 更新连接状态
            self.is_connected = False
            self._connection_established = False
            
            # 清理订阅状态（可选，根据业务需求决定）
            # for sub_type in self.subscription_status:
            #     self.subscription_status[sub_type].clear()
            
            logger.info("🔌 All WebSocket endpoints disconnected")
                
        except Exception as e:
            logger.error(f"❌ Error during disconnect: {e}")
            # 即使出错也要确保状态被重置
            self.is_connected = False
            self._connection_established = False
            
        
    async def _do_subscribe(self, market_ids: List[str], subscription_type: SubscriptionType):
        """实际执行订阅逻辑"""
        config = self.endpoint_configs[subscription_type]
        connector = self.connectors[subscription_type]
        
        if not connector.is_connected:
            return
        
        # 构建订阅消息
        if subscription_type in [SubscriptionType.ORDERBOOK, SubscriptionType.TRADES]:
            # CLOB 端点使用官方格式
            subscribe_msg = {
                "assets_ids": market_ids,  # 使用资产ID列表
                "type": "market"
            }
        else:
            # 其他端点保持原有格式
            subscribe_msg = self._build_subscribe_message(market_ids, subscription_type)
            logger.info(f"📡 订阅 {subscription_type.value}: {market_ids}")
        
        try:
            await connector.send_json(subscribe_msg)
            logger.info(f"📡 订阅 {subscription_type.value}: {market_ids}，msg: {subscribe_msg}")
            
            # 更新订阅状态
            for market_id in market_ids:
                self.subscription_status[subscription_type].add(market_id)
                
        except Exception as e:
            logger.error(f"❌ {subscription_type.value} 订阅失败: {e}")

    def _build_subscription_message(self, market_ids: List[str], subscription_type: SubscriptionType) -> Dict:
        """构建订阅消息"""
        config = self.endpoint_configs[subscription_type]
        base_message = config.message_format.copy()
        
        # 根据订阅类型处理市场ID
        if subscription_type in [SubscriptionType.ORDERBOOK, SubscriptionType.TRADES]:
            # CLOB 订阅需要为每个市场创建单独的订阅项
            base_message["subscriptions"] = [
                {
                    **subscription,
                    "filters": subscription["filters"].format(market_id=market_id)
                }
                for market_id in market_ids
                for subscription in base_message["subscriptions"]
            ]
        
        return base_message        

    def _initialize_subscription_state(self, market_ids: List[str], subscription_type: SubscriptionType):
        """根据订阅类型初始化状态"""
        if subscription_type == SubscriptionType.ORDERBOOK:
            # 为订单簿订阅初始化状态
            for market_id in market_ids:
                if market_id not in self.orderbook_snapshots:
                    # 初始化空的订单簿
                    self.orderbook_snapshots[market_id] = OrderBook(
                        bids=[],
                        asks=[],
                        timestamp=datetime.now(timezone.utc),
                        symbol=market_id
                    )
                    self.last_sequence_nums[market_id] = 0
                    self.pending_updates[market_id] = []
                    
                    logger.debug(f"📊 初始化订单簿状态: {market_id}")
        
        elif subscription_type == SubscriptionType.TRADES:
            # 为交易订阅初始化状态（如果需要）
            for market_id in market_ids:
                if market_id not in self.trade_history:
                    self.trade_history[market_id] = []
                    logger.debug(f"💹 初始化交易历史状态: {market_id}")
        
        elif subscription_type == SubscriptionType.PRICES:
            # 为价格订阅初始化状态
            if not hasattr(self, 'price_snapshots'):
                self.price_snapshots = {}
            
            logger.debug("💰 初始化价格订阅状态")
        
        elif subscription_type == SubscriptionType.COMMENTS:
            # 为评论订阅初始化状态
            if not hasattr(self, 'comment_streams'):
                self.comment_streams = {}
            
            logger.debug("💬 初始化评论订阅状态")

    def _cleanup_subscription_state(self, market_ids: List[str], subscription_type: SubscriptionType):
        """清理订阅状态"""
        if subscription_type == SubscriptionType.ORDERBOOK:
            # 清理订单簿状态
            for market_id in market_ids:
                self.orderbook_snapshots.pop(market_id, None)
                self.last_sequence_nums.pop(market_id, None)
                self.pending_updates.pop(market_id, None)
                
        elif subscription_type == SubscriptionType.TRADES:
            # 清理交易状态
            for market_id in market_ids:
                self.trade_history.pop(market_id, None)
                
        elif subscription_type == SubscriptionType.PRICES:
            # 价格状态通常是全局的，不需要清理特定市场
            pass
            
        elif subscription_type == SubscriptionType.COMMENTS:
            # 评论状态通常是全局的
            pass
            
    async def _do_unsubscribe(self, market_ids: List[str], subscription_type: SubscriptionType):
        """执行特定类型的取消订阅"""
        config = self.endpoint_configs[subscription_type]
        connector = self.connectors[subscription_type]
        
        if not connector.is_connected:
            return
        
        # 构建取消订阅消息
        unsubscribe_msg = self._build_unsubscribe_message(market_ids, subscription_type)
        
        try:
            await connector.send_json(unsubscribe_msg)
            logger.info(f"📡 取消订阅 {subscription_type.value}: {market_ids}")
            
            # 清理订阅状态
            self._cleanup_subscription_state(market_ids, subscription_type)
            
            # 更新订阅状态
            for market_id in market_ids:
                self.subscription_status[subscription_type].discard(market_id)
                
        except Exception as e:
            logger.error(f"❌ {subscription_type.value} 取消订阅失败: {e}")
            
    def _handle_raw_message(self, raw_data):
        """处理原始WebSocket消息 - 毫秒级性能"""
        try:
            self.message_count += 1
            current_time = datetime.now(timezone.utc)
            
            # 性能监控
            if self.last_message_time:
                latency = (current_time - self.last_message_time).total_seconds() * 1000
                self.performance_stats["average_latency"] = (
                    self.performance_stats["average_latency"] * 0.9 + latency * 0.1
                )
            self.last_message_time = current_time
            
            # 处理不同类型的消息格式
            if isinstance(raw_data, list):
                # 如果是数组格式，逐个处理每个元素
                if not raw_data:  # 空数组
                    logger.debug("收到空数组消息，可能是心跳或订阅确认，忽略")
                    return
                    
                logger.debug(f"处理数组消息，包含 {len(raw_data)} 个元素")
                for item in raw_data:
                    # 对数组中的每个元素，递归调用自己
                    self._handle_raw_message(item)
                return
                    
            # 如果是字典格式，继续原来的处理逻辑
            message_type = raw_data.get('event_type')
            market_id = raw_data.get('market')
            
            if not market_id:
                return
                
            logger.info(f"📨 Received {message_type} for {market_id}")
            
            # 根据消息类型处理
            if message_type == 'book':
                self._handle_orderbook_update(raw_data)
            elif message_type == 'trade':
                self._handle_trade_update(raw_data)
            elif message_type == 'price_change':
                self._handle_price_change_update(raw_data)
            elif message_type == 'heartbeat':
                self._handle_heartbeat(raw_data)
            elif message_type == 'error':
                self._handle_error(raw_data)
            else:
                logger.warning(f"❓ Unknown message type: {message_type}, raw message: {raw_data}")
                    
        except Exception as e:
            logger.error(f"❌ Error processing WebSocket message: {e}")
            
    def _handle_orderbook_update(self, data: Dict):
        """处理订单簿更新 - 高性能版本"""
        try:
            market_id = data['market']
            timestamp = data.get('timestamp', 0)
            bids = data.get('bids', [])
            asks = data.get('asks', [])
            
            # 检查序列号连续性
            sequence_num = int(timestamp) if timestamp and str(timestamp).isdigit() else 0
            last_seq = self.last_sequence_nums.get(market_id, 0)
            if sequence_num <= last_seq:
                logger.warning(f"🔍 Skipping old update for {market_id}: {sequence_num} <= {last_seq}")
                return
                
            # 更新订单簿
            self._update_orderbook(market_id, bids, asks, sequence_num)
            
            # 生成市场数据
            logger.info(f"To create market data for {market_id}")
            market_data = self._create_market_data(market_id)
            if market_data:
                logger.info(f"Callback for {market_data}")
                self._notify_callbacks(market_data)
                
            logger.info(f"✅ Orderbook updated for {market_id}: {len(bids)} bids, {len(asks)} asks")
            
        except Exception as e:
            logger.error(f"❌ Error processing orderbook update: {e}")
            
    def _update_orderbook(self, market_id: str, bids: List, asks: List, sequence_num: int):
        """更新订单簿状态"""
        try:
            # 转换 bids - 修复这里
            bid_levels = []
            for bid in bids:
                bid_levels.append(OrderBookLevel(
                    price=Decimal(str(bid['price'])),
                    quantity=Decimal(str(bid['size']))
                ))
            
            # 转换 asks - 修复这里
            ask_levels = []
            for ask in asks:
                ask_levels.append(OrderBookLevel(
                    price=Decimal(str(ask['price'])),
                    quantity=Decimal(str(ask['size']))
                ))
            
            # 排序
            bid_levels.sort(key=lambda x: x.price, reverse=True)
            ask_levels.sort(key=lambda x: x.price)
            
            # 限制深度
            bid_levels = bid_levels[:20]
            ask_levels = ask_levels[:20]
            
            # 更新订单簿快照
            self.orderbook_snapshots[market_id] = OrderBook(
                bids=bid_levels,
                asks=ask_levels,
                timestamp=datetime.now(timezone.utc),
                symbol=market_id
            )
            
            self.last_sequence_nums[market_id] = sequence_num
            
        except Exception as e:
            logger.error(f"❌ Error updating orderbook: {e}")
            # 添加更详细的错误信息
            logger.error(f"Bids: {bids}")
            logger.error(f"Asks: {asks}")
            
    def _handle_trade_update(self, data: Dict):
        """处理交易更新"""
        try:
            market_id = data['market']
            price = Decimal(data['price'])
            quantity = Decimal(data['quantity'])
            side = data['side']  # 'buy' or 'sell'
            timestamp = datetime.fromtimestamp(data['timestamp'] / 1000, tz=timezone.utc)
            
            # 创建 Trade 对象
            trade = Trade(
                trade_id=f"{market_id}_{timestamp.timestamp()}",  # 生成一个简单的交易ID
                price=price,
                quantity=quantity,
                timestamp=timestamp,
                is_buyer_maker=(side == 'sell')  # 如果是买单，则卖方是maker；如果是卖单，则买方是maker
            )
            
            # 创建 MarketData 对象，使用 last_trade 字段
            market_data = MarketData(
                symbol=market_id,
                exchange=ExchangeType.POLYMARKET,
                market_type=MarketType.PREDICTION,
                timestamp=timestamp,
                last_price=price,
                last_trade=trade
            )
            
            self._notify_callbacks(market_data)
            
            logger.info(f"💹 Trade update for {market_id}: {side} {quantity} @ {price}")
            
        except Exception as e:
            logger.error(f"❌ Error processing trade update: {e}")

    def _handle_price_change_update(self, data: Dict):
        """处理价格变动更新"""
        try:
            market_id = data.get('market')
            price_changes = data.get('price_changes', [])
            timestamp = data.get('timestamp')
            
            if not market_id or not price_changes:
                logger.warning(f"价格变动消息缺少必要字段: market_id={market_id}, price_changes={len(price_changes)}")
                return
                
            logger.info(f"📊 处理价格变动消息: {market_id}, 包含 {len(price_changes)} 个资产")
            
            for price_change in price_changes:
                asset_id = price_change.get('asset_id')
                price = price_change.get('price')
                size = price_change.get('size')
                side = price_change.get('side')  # BUY 或 SELL
                best_bid = price_change.get('best_bid')
                best_ask = price_change.get('best_ask')
                
                if not all([asset_id, price, side]):
                    logger.warning(f"价格变动数据不完整: {price_change}")
                    continue
                    
                # 创建价格变动数据对象
                price_change_data = {
                    'market': market_id,
                    'asset_id': asset_id,
                    'price': price,
                    'size': size,
                    'side': side,
                    'best_bid': best_bid,
                    'best_ask': best_ask,
                    'timestamp': timestamp,
                    'event_type': 'price_change'
                }
                
                # 生成市场数据
                logger.debug(f"为资产 {asset_id} 生成市场数据")
                market_data = self._create_market_data(price_change_data)
                if market_data:
                    logger.info(f"价格变动回调: {market_data}")
                    self._notify_callbacks(market_data)
                
                # 如果需要，可以更新本地订单簿的最优报价
                if best_bid and best_ask:
                    self._update_market_best_prices(market_id, asset_id, best_bid, best_ask)
                    
            logger.info(f"✅ 价格变动处理完成: {market_id}")
            
        except Exception as e:
            logger.error(f"❌ Error processing price change update: {e}")

    def _update_market_best_prices(self, market_id: str, asset_id: str, best_bid: str, best_ask: str):
        """更新市场最优报价"""
        try:
            # 这里可以更新本地维护的最优买卖价缓存
            # 例如：self.best_prices[market_id][asset_id] = {'bid': best_bid, 'ask': best_ask}
            
            logger.debug(f"更新最优报价: market={market_id}, asset={asset_id}, bid={best_bid}, ask={best_ask}")
            
        except Exception as e:
            logger.error(f"更新最优报价失败: {e}")        
            
    def _handle_heartbeat(self, data: Dict):
        """处理心跳消息"""
        # 可以在这里更新连接健康状态
        pass
        
    def _handle_error(self, data: Dict):
        """处理错误消息"""
        error_msg = data.get('message', 'Unknown error')
        logger.error(f"❌ WebSocket error: {error_msg}")
        
    def _create_market_data(self, market_id: str) -> Optional[MarketData]:
        """从订单簿快照创建市场数据"""
        try:
            orderbook = self.orderbook_snapshots.get(market_id)
            if not orderbook:
                return None
                
            market_data = MarketData(
                symbol=market_id,
                exchange=ExchangeType.POLYMARKET,
                market_type=MarketType.PREDICTION,
                timestamp=datetime.now(timezone.utc),
                orderbook=orderbook
            )
            
            return market_data
            
        except Exception as e:
            logger.error(f"❌ Error creating market data: {e}")
            return None
            
    def _handle_connection_error(self, st, error: Exception):
        """处理连接错误"""
        logger.error(f"❌ Polymarket WebSocket connection for {st} error: {error}")
        self.is_connected = False
        self._connection_established = False

        # TODO: 因为是多链接，所以要关闭所有连接之后再全部重连，或者只重连自己这一个连接
        
        # 触发重连逻辑
        asyncio.create_task(self._attempt_reconnect())
        
    async def _attempt_reconnect(self):
        """尝试重新连接 - 多连接器版本"""
        logger.info("🔄 Attempting to reconnect to all WebSocket endpoints...")
        await asyncio.sleep(2)  # 较短的重连延迟
        
        try:
            success = await self.connect()
            if success:
                # 重新订阅所有已注册的交易对（多连接器版本）
                await asyncio.sleep(1)
                await self._resubscribe_all()  # 复用现有的重新订阅逻辑
        except Exception as e:
            logger.error(f"❌ Reconnection attempt failed: {e}")
            
    async def _performance_monitor(self):
        """性能监控循环"""
        while self.is_connected:
            try:
                # 计算每秒消息数
                current_time = datetime.now(timezone.utc)
                time_diff = (current_time - self.performance_stats["last_update"]).total_seconds()
                
                if time_diff >= 1.0:  # 每秒更新一次
                    self.performance_stats["messages_per_second"] = self.message_count / time_diff
                    self.message_count = 0
                    self.performance_stats["last_update"] = current_time
                    
                    # 记录性能指标（可选）
                    if self.performance_stats["messages_per_second"] > 10:  # 高频率时才记录
                        logger.debug(
                            f"📊 Performance: {self.performance_stats['messages_per_second']:.1f} msg/s, "
                            f"latency: {self.performance_stats['average_latency']:.2f}ms"
                        )
                
                await asyncio.sleep(1)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"❌ Performance monitor error: {e}")
                await asyncio.sleep(5)
                
    def normalize_data(self, raw_data: Dict) -> Optional[MarketData]:
        """标准化数据 - WebSocket版本"""
        # WebSocket版本中，数据已经在_handle_raw_message中处理
        return None
        
    def get_connection_status(self) -> Dict:
        """获取所有连接的详细状态"""
        # 计算全局连接状态（所有连接器都连接才算真正连接）
        global_connected = all(connector.is_connected for connector in self.connectors.values())
        
        # 汇总所有订阅的市场
        all_subscribed_markets = set()
        for markets in self.subscription_status.values():
            all_subscribed_markets.update(markets)
        
        # 基础状态
        base_status = {
            "name": self.name,
            "exchange": self.exchange_type.value,
            "is_connected": global_connected,  # 使用全局连接状态
            "connection_established": self._connection_established,
            "subscribed_symbols": list(all_subscribed_markets),  # 汇总所有订阅
            "callback_count": len(self.callbacks)
        }
        
        # 多连接器详细信息
        connection_details = {}
        performance_summary = {
            "messages_per_second": 0,
            "average_latency_ms": 0,
            "total_messages": 0
        }
        
        for sub_type, connector in self.connectors.items():
            # 获取每个连接器的状态
            connector_info = connector.get_connection_info() if hasattr(connector, 'get_connection_info') else {}
            
            connection_details[sub_type.value] = {
                "endpoint": self.endpoint_configs[sub_type].endpoint,
                "is_connected": connector.is_connected,
                "subscribed_markets": list(self.subscription_status[sub_type]),
                "connector_info": connector_info
            }
            
            # 汇总性能指标（如果有）
            if hasattr(connector, 'performance_stats'):
                connector_perf = connector.performance_stats
                performance_summary["messages_per_second"] += connector_perf.get("messages_per_second", 0)
                performance_summary["average_latency_ms"] += connector_perf.get("average_latency", 0)
                performance_summary["total_messages"] += connector_perf.get("message_count", 0)
        
        # 计算平均延迟
        connected_count = sum(1 for connector in self.connectors.values() if connector.is_connected)
        if connected_count > 0:
            performance_summary["average_latency_ms"] = round(
                performance_summary["average_latency_ms"] / connected_count, 2
            )
        
        return {
            **base_status,
            "performance": performance_summary,
            "orderbook_snapshots_count": len(self.orderbook_snapshots),
            "pending_updates_count": sum(len(updates) for updates in self.pending_updates.values()),
            "connection_details": connection_details
        }
        
    async def get_market_list(self, close: bool = False, limit: int = 50) -> List[Dict]:
        """获取可用市场列表 - 使用正确的筛选参数"""
        try:
            # 使用封装的 RESTConnector（自动处理代理）
            async with RESTConnector(
                base_url=self.rest_urls[0],
                timeout=10,
                name="polymarket_rest"
            ) as connector:
                
                # 使用正确的参数获取活跃市场
                params = {
                    "limit": limit,
                    "closed": "false" if not close else "true",  # 关键：只获取未关闭的市场
                    "order": "volumeNum",  # 按交易量排序
                    "ascending": "false",  # 降序排列（交易量大的在前）
                }
                
                response = await connector.get(
                    "/markets",
                    params=params
                )
                
                if response.status == 200:
                    markets = await response.json()
                    
                    # 记录获取到的市场状态
                    active_count = sum(1 for m in markets if m.get('closed') is False)
                    
                    logger.info(f"✅ 成功获取 {len(markets)} 个活跃市场")
                    
                    # 打印前几个市场的详细信息用于调试
                    for i, market in enumerate(markets[:3]):
                        logger.info(f"  市场 {i+1}: ID={market.get('id')}, 交易量={market.get('volumeNum')}, 问题={market.get('question', '')[:50]}...")
                        logger.info(f"    结束时间: {market.get('endDate')}")
                        if market.get('clobTokenIds'):
                            try:
                                token_ids = json.loads(market['clobTokenIds'])
                                logger.info(f"    Token IDs: {token_ids[:1]}...")  # 只显示第一个token
                            except:
                                logger.info(f"    Token IDs: 解析失败")
                    
                    return markets
                else:
                    error_text = await response.text()
                    logger.error(f"❌ 获取市场列表失败: HTTP {response.status} - {error_text}")
                    return []
                                
        except aiohttp.ClientError as e:
            logger.error(f"❌ 网络错误获取市场列表: {e}")
            return []
        except Exception as e:
            logger.error(f"❌ 未知错误获取市场列表: {e}")
            return []
        
    async def get_active_market(self, limit: int = 50) -> List[Dict]:
        return await self.get_market_list(False, limit)
        
    async def subscribe(self, symbols: list, subscription_type: SubscriptionType = SubscriptionType.ORDERBOOK):
        """重写订阅方法以支持多连接器"""
        new_symbols = set(symbols) - self.subscription_status[subscription_type]
        if new_symbols:
            await self._do_subscribe(list(new_symbols), subscription_type)
            self.subscription_status[subscription_type].update(new_symbols)
    
    async def unsubscribe(self, symbols: list, subscription_type: SubscriptionType = SubscriptionType.ORDERBOOK):
        """重写取消订阅方法以支持多连接器"""
        to_remove = set(symbols) & self.subscription_status[subscription_type]
        if to_remove:
            await self._do_unsubscribe(list(to_remove), subscription_type)
            self.subscription_status[subscription_type] -= to_remove

    async def subscribe_orderbook(self, symbols: list):
        """便捷方法：订阅订单簿数据"""
        await self.subscribe(symbols, SubscriptionType.ORDERBOOK)
    
    async def subscribe_trades(self, symbols: list):
        """便捷方法：订阅交易数据"""
        await self.subscribe(symbols, SubscriptionType.TRADES)
    
    async def subscribe_prices(self, symbols: list):
        """便捷方法：订阅价格数据"""
        await self.subscribe(symbols, SubscriptionType.PRICES)            
         