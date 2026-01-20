import asyncio
import json
import time
from decimal import Decimal
from datetime import datetime, timezone
from collections import deque, defaultdict
from typing import Optional, List, Dict, Deque
import aiohttp
from enum import Enum
from dataclasses import dataclass

from logger.logger import get_logger
from .base_adapter import BaseAdapter
from ..service.ws_connector import WebSocketConnector
from ..service.rest_connector import RESTConnector
from ..core.data_models import MarketMeta, MarketData, OrderBook, OrderBookLevel, ExchangeType, TradeTick, PriceChange, MakerOrder, Trade
from ..monitor.collector import MarketMonitor

logger = get_logger()

class SubscriptionType(Enum):
    """订阅类型枚举"""
    ORDERBOOK = "orderbook"      #market channel订单簿数据
    TRADE = "trade"           # User channel交易数据
    PRICE = "price"      # Binance 价格
    PRICE_CHAINLINK = "price_chainlink"  # Chainlink 价格
    COMMENT = "comment"           # 评论数据

class WSEndpoint(Enum):
    """订阅类型枚举"""
    MARKET_CHANNEL = "wss://ws-subscriptions-clob.polymarket.com/ws/market" 
    USER_CHANNEL = "wss://ws-subscriptions-clob.polymarket.com/ws/user"
    RTDS = "wss://ws-live-data.polymarket.com"

@dataclass
class CachedMarket:
    """包含所有缓存信息的单一类"""
    __slots__ = ['meta', 'timestamp']
    
    meta: MarketMeta
    timestamp: float
    
    def is_expired(self, ttl: int) -> bool:
        return time.time() - self.timestamp > ttl    
'''    
class PerformanceMonitor:
    """延迟监控器"""
    
    def __init__(self, window_size: int = 1000):
        # 延迟历史窗口
        self.window_size = window_size
        self.latency_history: Dict[str, Deque[float]] = defaultdict(
            lambda: deque(maxlen=window_size)
        )
        
        # 实时统计
        self.realtime_stats = {
            "orderbook": self._init_message_stats(),
            "last_trade_price": self._init_message_stats(),
            "price_change": self._init_message_stats(),
            "all": self._init_message_stats()
        }
        
    def _init_message_stats(self) -> Dict:
        """初始化消息统计数据结构"""
        return {
            "count": 0,
            "last_time": None,
            "latency_ewma": 0.0,      # 指数加权平均
            "latency_p50": 0.0,       # 中位数
            "latency_p95": 0.0,       # 95百分位
            "latency_p99": 0.0,       # 99百分位
            "latency_min": float('inf'),
            "latency_max": 0.0,
            "throughput_1s": 0.0,     # 每秒消息数
            "throughput_1m": 0.0,     # 每分钟消息数
            "last_update": None,
            "errors": 0
        }    
'''

class PolymarketAdapter(BaseAdapter):
    """Polymarket WebSocket 适配器 - 毫秒级性能"""
    
    def __init__(self):
        super().__init__("polymarket", ExchangeType.POLYMARKET)

        # 市场数据状态
        self.orderbook_snapshots: Dict[str, OrderBook] = {} # asset_id -> 最新订单薄，对用BOOK消息
        self.last_trade_prices: Dict[str, TradeTick] = {}    # asset_id -> 最后成交信息，对应last_trade_price消息
        self.price_changes: Dict[str, Deque[PriceChange]] = {} # asset_id -> 价格变化信息信息，对应price_change消息
        self.trade_history: Dict[str, List[Trade]] = {}  # asset_id -> 交易历史列表se

        # 计算聚合数据
        self.last_prices= {}    # asset_id -> 最后价格信息，last_trade_price消息和price_change消息都会更新
        self.best_prices= {}    # asset_id -> 最优价格信息

        # 🎯 缓存系统：只缓存核心数据
        self.market_cache = {}  # market_id -> CachedMarket
        self.token_cache = {}   # token_id -> market_id
        self.cache_ttl_seconds = 3600  # 1小时缓存过期
        
        # 性能监控
        self.message_count = 0
        self.last_message_time = None
        self.monitor = MarketMonitor()
        # 时钟同步状态（用于校准）
        self.clock_offset_ms = 0  # 本地时钟 - 服务器时钟#

        self.rest_urls = [
            "https://gamma-api.polymarket.com",
            "https://clob.polymarket.com/markets",
        ]

        # 映射：我的逻辑订阅类型 -> 物理端点
        self._subscription_config = {
            SubscriptionType.ORDERBOOK: {
                'endpoint': WSEndpoint.MARKET_CHANNEL,
                'protocol': 'clob',  # 新增字段：标识协议类型
                'message_format': {
                    "assets_ids": [],  # 将在_build_subscribe_message中填充
                    "type": "market"
                }
            },
            SubscriptionType.TRADE: {
                'endpoint': WSEndpoint.USER_CHANNEL,
                'protocol': 'clob',
                'message_format': {
                    "assets_ids": [],
                    "type": "market"  # 注意：USER通道可能使用相同格式
                }
            },
            SubscriptionType.PRICE: {
                'endpoint': WSEndpoint.RTDS,
                'protocol': 'rtds',
                'message_format': {
                    "action": "subscribe",
                    "subscriptions": [
                        {
                            "topic": "crypto_prices",
                            "type": "update",
                            "filters": "solusdt,btcusdt,ethusdt"
                        }
                    ]
                }
            },
            SubscriptionType.PRICE_CHAINLINK: {
                'endpoint': WSEndpoint.RTDS,
                'protocol': 'rtds',
                'message_format': {
                    "action": "subscribe",
                    "subscriptions": [
                        {
                            "topic": "crypto_prices_chainlink",
                            "type": "*",
                            "filters": ""
                        }
                    ]
                }
            },
            SubscriptionType.COMMENT: {
                'endpoint': WSEndpoint.RTDS,  # 与PRICES共享连接
                'protocol': 'rtds',
                'message_format': {
                    "action": "subscribe",
                    "subscriptions": [
                        {
                            "topic": "comments",
                            "type": "comment_created"
                        }
                    ]
                }
            }
        }

        # 多个 WebSocket 连接器
        self.connectors: Dict[SubscriptionType, WebSocketConnector] = {}
        self.subscription_status: Dict[SubscriptionType, set] = {} #CLOB协议：asset id；RTDS协议：symbol
        self.subscribed_markets: Dict[SubscriptionType, set] = {} # market集合
        self.subscribed_topics: Dict[SubscriptionType, set] = {}   # topic集合

        # 初始化连接器和状态
        self.is_connected = False
        for sub_type in SubscriptionType:
            # 获取此订阅类型的配置
            config = self._subscription_config[sub_type]
            endpoint = config['endpoint']
            
            # 创建新的连接器
            connector = WebSocketConnector(
                url=endpoint.value,  # 使用枚举的value属性获取URL字符串
                on_message=lambda msg, st=sub_type: self._handle_raw_message(msg),
                on_error=lambda err, st=sub_type: self._handle_connection_error(err, st),
                ping_interval=20,
                timeout=5,
                name=f"polymarket_{sub_type.value}"  # 名称仍保持唯一，便于调试
            )
            logger.debug(f"创建新连接器 {endpoint.value} 给 {sub_type.value}")
            
            # 存储到按订阅类型索引的字典中（PRICE和COMMENT会指向同一个connector对象）
            self.connectors[sub_type] = connector
            self.subscription_status[sub_type] = set()
            self.subscribed_markets[sub_type] = set()
            self.subscribed_topics[sub_type] = set()

        # 扩展状态管理
        self._initialize_all_states()

        unique_connectors = len({id(conn) for conn in self.connectors.values()})
        logger.info(f"初始化完成: {len(SubscriptionType)} 个订阅")

    def _initialize_all_states(self):
        """初始化所有状态容器"""
        # 订单簿相关状态（从基类继承，确保存在）
        if not hasattr(self, 'orderbook_snapshots'):
            self.orderbook_snapshots = {}
        
        # 交易相关状态
        self.trade_history = {}  # market_id -> List[Trade]
        
        # 价格相关状态
        self.price_snapshots = {}  # symbol -> PriceSnapshot
        
        # 评论相关状态
        self.comment_streams = {}  # stream_id -> CommentStream
        
        # 性能监控
        self.message_count_by_type = {sub_type: 0 for sub_type in SubscriptionType}        

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
                logger.info("✅ All WebSocket endpoints connected successfully")
                
                # 连接成功后立即订阅已注册的交易对
                if any(self.subscription_status.values()):
                    await asyncio.sleep(0.5)  # 给连接一点时间稳定
                    await self._resubscribe_all()

                # 更新监控指标
                if self.monitor:
                    self._record_connection_event(self.is_connected)
                
                return True
            else:
                logger.error("❌ Some WebSocket endpoints failed to connect")
                self.is_connected = False
                # 更新监控指标
                if self.monitor:
                    self._record_connection_event(self.is_connected)
                return False
                
        except Exception as e:
            logger.exception(f"❌ WebSocket connection failed: {e}")
            self.is_connected = False
            # 更新监控指标
            if self.monitor:
                self._record_connection_event(self.is_connected)

            return False
        
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
            
            # 清理订阅状态（可选，根据业务需求决定）
            # for sub_type in self.subscription_status:
            #     self.subscription_status[sub_type].clear()
            
            logger.info("🔌 All WebSocket endpoints disconnected")
                
        except Exception as e:
            logger.error(f"❌ Error during disconnect: {e}")
            # 即使出错也要确保状态被重置
            self.is_connected = False

    '''
         # === 统一的底层方法 ===
    '''     
    async def _send_subscription_action(self, subscription_type: SubscriptionType, action: str, payload: dict = None):
        """核心方法：执行订阅/取消订阅动作"""
        config = self._subscription_config[subscription_type]
        connector = self.connectors[subscription_type]

        if not connector.is_connected:
            logger.error(f"❌ 连接器未就绪: {subscription_type.value}")
            return

        # 构建消息（CLOB 和 RTDS 格式差异在此处理）
        message = self._build_websocket_message(subscription_type, action, payload)
        if not message:
            return

        logger.info(f"📡 {action} {subscription_type.value}: 消息已构建")

        try:
            await connector.send_json(message)
            logger.info(f"✅ 已发送 {action} 请求: {subscription_type.value}")
            return True
        except Exception as e:
            logger.error(f"❌ {action} 失败 {subscription_type.value}: {e}")
            return False

    def _build_websocket_message(self, subscription_type: SubscriptionType, action: str, payload: dict = None) -> Dict:
        """构建 WebSocket 消息（区分 CLOB 和 RTDS 格式）"""
        config = self._subscription_config[subscription_type]
        protocol = config['protocol']

        if protocol == 'clob':
            # CLOB 格式: {"assets_ids": [...], "type": "market" 或 "unsubscribe"}
            asset_ids = payload.get('asset_ids', []) if payload else []
            return {
                "assets_ids": asset_ids,
                "type": action  # 这里 action 可以是 'market'（订阅）或 'unsubscribe'
            }
        elif protocol == 'rtds':
            # RTDS 格式: {"action": "...", "subscriptions": [...]}
            base_message = config['message_format'].copy()
            base_message['action'] = action  # 'subscribe' 或 'unsubscribe'
            
            # 如果有 payload，可以动态修改 subscriptions（例如添加 filters）
            if payload and 'subscriptions' in payload:
                # 允许外部传入定制的 subscriptions 数组来覆盖默认配置
                base_message['subscriptions'] = payload['subscriptions']
            
            return base_message
        else:
            logger.error(f"❌ 未知协议类型: {protocol}")
            return {}   

    '''
        CLOB订阅接口
    '''   
    async def _do_subscribe(self, asset_ids: List[str], subscription_type: SubscriptionType):
        """实际执行订阅逻辑"""
        config = self._subscription_config[subscription_type]
        connector = self.connectors[subscription_type]
        
        if not self.is_connected or not connector.is_connected:
            return
        
        # 计算新的 asset_ids（去重，排除已订阅的）
        already_subscribed = self.subscription_status[subscription_type]
        new_asset_ids = set(asset_ids) - already_subscribed
        
        if not new_asset_ids:
            logger.info(f"📡 代币 {asset_ids} 已全部订阅，无需重复订阅")
            return
        
        try:
            success = await self._send_subscription_action(
                subscription_type=subscription_type,
                action='market',  # CLOB 订阅的固定 action
                payload={'asset_ids': list(asset_ids)}
            )
            
            # 更新订阅状态
            if success:
                for asset_id in asset_ids:
                    self.subscription_status[subscription_type].add(asset_id)
                    self.subscribed_symbols.add(asset_id)
                
        except Exception as e:
            logger.error(f"❌ {subscription_type.value} 订阅失败: {e}")
    
    async def subscribe(self, market_ids: list, subscription_type: SubscriptionType = SubscriptionType.ORDERBOOK):
        if subscription_type not in [SubscriptionType.ORDERBOOK, SubscriptionType.TRADE]:
            logger.warning("⚠️ 调用接口错误，跳过")
            return
        if not market_ids:
            logger.warning("⚠️ 订阅请求为空，跳过")
            return
        
        logger.info(f"📡 订阅 {subscription_type.value}: {market_ids}")
        
        # 确保 market_ids 是列表
        if isinstance(market_ids, str):
            market_ids = [market_ids]
        
        # 1. 将 market_ids 转换为 asset_ids（代币ID）
        asset_ids = []
        missing_markets = []
        
        for market_id in market_ids:
            # 从缓存获取市场对应的代币ID
            tokens = self.get_market_tokens(market_id)
            if tokens:
                asset_ids.extend(tokens)
                logger.info(f"市场 {market_id} -> {len(tokens)} 个代币ID: {tokens}")
            else:
                missing_markets.append(market_id)
        
        # 如果有市场没有找到代币ID，记录警告
        if missing_markets:
            logger.warning(f"⚠️ 无法找到以下市场的代币ID，将跳过订阅: {missing_markets}")
        
        if not asset_ids:
            logger.error(f"❌ 没有可用的代币ID进行订阅: {market_ids}")
            return
        
        # 3. 执行订阅
        logger.info(f"📡 订阅 {subscription_type.value}: {market_ids} -> {len(asset_ids)} 个代币")
        
        # 调用原有的 _do_subscribe 方法
        await self._do_subscribe(list(asset_ids), subscription_type)
        
        # 4. 更新订阅状态（_do_subscribe 内部已经更新代币，这里仅更新market）
        for market_id in market_ids:
            self.subscribed_markets[subscription_type].add(market_id)
    
    async def _do_unsubscribe(self, asset_ids: list, subscription_type: SubscriptionType = SubscriptionType.ORDERBOOK):
        """取消订阅 CLOB 数据 (ORDERBOOK, TRADE)"""
        
        # 1. 计算需要取消订阅的 asset_ids
        to_remove_asset = set(asset_ids) & self.subscription_status[subscription_type]
        if not to_remove_asset:
            logger.info(f"📭 没有找到活跃的代币订阅: {asset_ids}")
            return
        
        # 2. 调用底层方法发送取消订阅消息
        success = await self._send_subscription_action(
            subscription_type=subscription_type,
            action='unsubscribe',  # CLOB 取消订阅的 action
            payload={'asset_ids': list(to_remove_asset)}
        )
        
        # 5. 更新状态（仅在成功后）
        if success:
            # 清理 asset_ids 状态
            self.subscription_status[subscription_type] -= to_remove_asset
            
            logger.info(f"✅ CLOB 取消订阅成功: {subscription_type.value} - {len(to_remove_asset)} 个代币")     

    async def unsubscribe(self, market_ids: list, subscription_type: SubscriptionType = SubscriptionType.ORDERBOOK):
        """取消订阅 CLOB 数据 (ORDERBOOK, TRADE)"""
        # 1. 类型校验：只允许CLOB类型
        if subscription_type not in [SubscriptionType.ORDERBOOK, SubscriptionType.TRADE]:
            logger.error(f"❌ 协议不匹配: {subscription_type.value} 请使用 unsubscribe_rtds 方法")
            return
        
        if not market_ids:
            logger.warning("⚠️ 取消订阅请求为空，跳过")
            return
        
        logger.info(f"📡 取消订阅 {subscription_type.value}: {market_ids}")
        
        # 确保 market_ids 是列表
        if isinstance(market_ids, str):
            market_ids = [market_ids]
        
        # 2. 将 market_ids 转换为 asset_ids（代币ID）
        asset_ids = []
        missing_markets = []
        
        for market_id in market_ids:
            # 从缓存获取市场对应的代币ID
            tokens = self.get_market_tokens(market_id)
            if tokens:
                asset_ids.extend(tokens)
                logger.info(f"市场 {market_id} -> {len(tokens)} 个代币ID: {tokens}")
            else:
                missing_markets.append(market_id)
        
        # 3. 如果有市场没有找到代币ID，记录警告
        if missing_markets:
            logger.warning(f"⚠️ 无法找到以下市场的代币ID，将跳过取消订阅: {missing_markets}")
        
        if not asset_ids:
            logger.error(f"❌ 没有可用的代币ID进行取消订阅: {market_ids}")
            return
        
        
        # 4. 调用底层方法发送取消订阅消息
        await self._do_unsubscribe(list(asset_ids), subscription_type)
        
        # 5. 更新状态, 清理 market_ids 状态
        to_remove_market = set(market_ids) & self.subscribed_markets[subscription_type]
        if to_remove_market:
            self.subscribed_markets[subscription_type] -= to_remove_market
            
        # 可选：清理其他相关状态（如 orderbook_snapshots）
        for market_id in market_ids:
            if market_id in self.orderbook_snapshots:
                del self.orderbook_snapshots[market_id]
            
        logger.info(f"✅ CLOB 取消订阅成功: {subscription_type.value} - {len(market_ids)} 个market")        

    '''
        RTDS接口
    '''    
    async def subscribe_rtds(self, subscription_type: SubscriptionType = SubscriptionType.PRICE, symbols: List[str] = None, filters: str = None):
        """订阅 RTDS 数据 (PRICE, COMMENT)
        
        Args:
            subscription_type: PRICE 或 COMMENT
            symbols: 可选的交易对列表 (例如 ['BTCUSDT', 'ETHUSDT'])
            filters: 可选的过滤条件字符串
        """
        if subscription_type not in [SubscriptionType.PRICE, SubscriptionType.COMMENT]:
            logger.error(f"❌ 协议不匹配: {subscription_type.value} 请使用 subscribe 方法")
            return

        # 准备 payload，用于动态构建 subscriptions
        payload = {}
        
        if symbols or filters:
            # 从配置中复制默认的 subscription 模板
            config = self._subscription_config[subscription_type]
            base_subscription = config['message_format']['subscriptions'][0].copy()
            topic = base_subscription['topic']  # 获取配置中的topic
            
            # 应用自定义 filters
            if filters:
                base_subscription['filters'] = filters
            elif symbols:
                # 如果没有指定 filters，但指定了 symbols，则构建一个 filters 字符串
                # 例如: symbol=BTCUSDT,ETHUSDT
                base_subscription['filters'] = f"symbol={','.join(symbols)}"
            
            payload['subscriptions'] = [base_subscription]

        # 调用底层方法发送订阅消息
        success = await self._send_subscription_action(
            subscription_type=subscription_type,
            action='subscribe',  # RTDS 订阅的 action 就是 'subscribe'
            payload=payload if payload else None
        )

        # 更新状态
        if success:
            # 对于 RTDS，我们可以用一个标志来记录整个主题的订阅状态
            self.subscribed_topics[subscription_type].add(topic)
        
            # 2. 记录symbols（如果有）
            if symbols:
                self.subscription_status[subscription_type].update(symbols)
                
            # 3. 如果有filters但没有symbols，我们可以记录filters的哈希值
            elif filters:
                # 将filters作为整体记录
                filter_hash = f"filter_{hash(filters) & 0xFFFFFFFF}"
                self.subscription_status[subscription_type].add(filter_hash)
                
            logger.info(f"✅ RTDS 订阅成功: {subscription_type.value}")    

    async def unsubscribe_rtds(self, subscription_type: SubscriptionType = SubscriptionType.PRICE):
        """取消订阅 RTDS 数据"""
        if subscription_type not in [SubscriptionType.PRICE, SubscriptionType.COMMENT]:
            logger.error(f"❌ 协议不匹配: {subscription_type.value}")
            return

        # 检查是否已订阅
        config = self._subscription_config[subscription_type]
        base_subscription = config['message_format']['subscriptions'][0].copy()
        topic = base_subscription['topic'] 
        if topic not in self.subscribed_topics[subscription_type]:
            logger.info(f"📭 未找到活跃订阅: {subscription_type.value}")
            return

        # 调用底层方法发送取消订阅消息 (注意：RTDS 取消订阅使用相同的消息格式，仅 action 不同)
        success = await self._send_subscription_action(
            subscription_type=subscription_type,
            action='unsubscribe'
        )

        if success:
            self.subscribed_markets[subscription_type].discard(topic)
            logger.info(f"✅ RTDS 取消订阅成功: {subscription_type.value}")
        

    '''
        连接管理接口
    ''' 
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
 
            
    def _cleanup_subscription_state(self, asset_ids: List[str], subscription_type: SubscriptionType):
        """清理订阅状态"""
        if subscription_type == SubscriptionType.ORDERBOOK:
            # 清理订单簿状态
            for asset_id in asset_ids:
                self.orderbook_snapshots.pop(asset_id, None)
                
        elif subscription_type == SubscriptionType.TRADE:
            # 清理交易状态
            for asset_id in asset_ids:
                self.trade_history.pop(asset_id, None)
                
        elif subscription_type == SubscriptionType.PRICE:
            # 价格状态通常是全局的，不需要清理特定市场
            pass
            
        elif subscription_type == SubscriptionType.COMMENT:
            # 评论状态通常是全局的
            pass
            
    '''
        消息处理接口
    '''
            
    def _handle_raw_message(self, raw_data):
        """处理原始WebSocket消息 - 毫秒级性能"""
        try:
            self.message_count += 1
            current_time = datetime.now(timezone.utc)
            receive_timestamp_ms = int(current_time.timestamp() * 1000)
            self.last_message_time = receive_timestamp_ms   
            
            
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
            market_id = raw_data.get('market', None)
            asset_id = raw_data.get('asset_id', None)
            # print("========>>>>>>>>message_type: ", message_type)
            # print("========>>>>>>>>current_time:", current_time, "receive_timestamp_ms: ", receive_timestamp_ms)
            # st = int(raw_data.get('timestamp'))
            # dt = datetime.fromtimestamp(st / 1000, tz=timezone.utc)
            # print("========>>>>>>>>server_time:", dt, "server_timestamp_ms: ", st)
            # print("========>>>>>>>>delta: ", current_time - dt)
            
            # 更新监控统计
            server_ts_str = raw_data.get('timestamp')
            if not server_ts_str:
                logger.error(f"raw data received error: {raw_data}")
                return
            server_timestamp_ms = int(server_ts_str)
            self._update_monitor_stats(message_type, server_timestamp_ms, receive_timestamp_ms)
 
                
            # 根据消息类型处理
            if message_type == 'book':
                if not asset_id:
                    return
                logger.debug(f"📨 收到订单簿更新: {asset_id}")
                self._handle_orderbook(raw_data, receive_timestamp_ms)

            elif message_type == 'price_change':
                if not market_id:
                    return
                logger.debug(f"📨 Received price change for {market_id}")
                self._handle_price_change(raw_data, receive_timestamp_ms)    
                
            elif message_type == 'last_trade_price':
                if not asset_id:
                    return
                logger.debug(f"💡 收到最新成交价: {asset_id} 价格 {raw_data.get('price')}")
                # 专门处理最新成交价
                self._handle_last_trade_price(raw_data, receive_timestamp_ms)
                
            elif message_type == 'trade': # user channel，暂不支持
                if not asset_id:
                    return
                logger.debug(f"🔄 收到交易状态更新: 交易ID {raw_data.get('id')}")
                # 专门处理详尽的交易状态更新
                self._handle_trade(raw_data)

            elif message_type == 'heartbeat':
                logger.debug(f"❤️  Received heartbeat")
                self._handle_heartbeat(raw_data)

            elif message_type == 'error':
                logger.error(f"❌ Received error: {raw_data}")
                self._handle_error(raw_data)

            else:
                logger.warning(f"❓ 未知消息类型: {message_type}")
                    
        except Exception as e:
            logger.exception(f"❌ Error processing WebSocket message: {e}")
            
    def _handle_orderbook(self, data: Dict, receive_timestamp: int):
        """处理订单簿更新 - 高性能版本"""
        try:
            asset_id = data['asset_id']
            timestamp = data.get('timestamp', 0)
            bids = data.get('bids', [])
            asks = data.get('asks', [])
            
            # 检查序列号连续性
            server_timestamp = int(timestamp) if timestamp and str(timestamp).isdigit() else 0
            last_orderbook = self.orderbook_snapshots.get(asset_id, {})
            if last_orderbook:
                last_timestamp = last_orderbook.server_timestamp
                if server_timestamp <= last_timestamp:
                    logger.warning(f"🔍 Skipping old update for {asset_id}: {server_timestamp} <= {last_timestamp}, last data: {last_orderbook}, current data: {data}")
                    return
                
            # 更新订单簿
            self._update_orderbook(asset_id, bids, asks, server_timestamp, receive_timestamp)
            
            # 生成市场数据
            logger.debug(f"To create market data for {asset_id}")
            orderbook = self.orderbook_snapshots.get(asset_id)
            market_data = self._create_market_data(symbol=asset_id, exchange=ExchangeType.POLYMARKET, orderbook=orderbook)
            if market_data:
                logger.debug(f"Callback for {market_data}")
                self._notify_callbacks(market_data)
                
            logger.debug(f"✅ Orderbook updated for {asset_id}: {len(bids)} bids, {len(asks)} asks")
            
        except Exception as e:
            logger.error(f"❌ Error processing orderbook update: {e}")
            
    def _update_orderbook(self, asset_id: str, bids: List, asks: List, server_timestamp: int, receive_timestamp: int):
        """更新订单簿状态"""
        try:
            # 转换 bids
            bid_levels = []
            for bid in bids:
                bid_levels.append(OrderBookLevel(
                    price=Decimal(str(bid['price'])),
                    quantity=Decimal(str(bid['size']))
                ))
            
            # 转换 asks
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
            self.orderbook_snapshots[asset_id] = OrderBook(
                bids=bid_levels,
                asks=ask_levels,
                server_timestamp=server_timestamp,
                receive_timestamp=receive_timestamp,
                symbol=asset_id
            )
            
        except Exception as e:
            logger.error(f"❌ Error updating orderbook: {e}")
            # 添加更详细的错误信息
            logger.error(f"Bids: {bids}")
            logger.error(f"Asks: {asks}")

    def _handle_last_trade_price(self, data: Dict, receive_timestamp: int):  # 函数重命名
        """处理最新成交价消息：更新市场公共行情"""
        try:
            # 注意：这里data来自`last_trade_price`消息，字段是`asset_id`和`market`
            asset_id = data['asset_id']  # 关键：使用asset_id作为key
            price = Decimal(data['price'])
            size = Decimal(data['size'])
            side = data['side']  # 注意：消息中是 'BUY'/'SELL'
            server_timestamp = int(data['timestamp'])
            
            # 1. 创建Trade对象（如果需要）
            trade = TradeTick(
                trade_id=f"{asset_id}_{server_timestamp}",
                symbol=asset_id,
                price=price,
                size=size,
                side = side,
                server_timestamp = server_timestamp,
                receive_timestamp = receive_timestamp,
                exchange=ExchangeType.POLYMARKET
            )
            
            self.last_trade_prices[asset_id] = trade
            
            # 2. 生成市场数据，触发回调
            # 你需要确保_create_market_data能通过asset_id找到对应订单簿，并填入last_price
            market_data = self._create_market_data(
                symbol=asset_id,
                exchange=ExchangeType.POLYMARKET,
                last_price=price,
                last_trade=trade
            )
            if market_data:
                self._notify_callbacks(market_data)
                logger.debug(f"📈 最新价更新 {asset_id}: {side} {size} @ {price}")
                
        except Exception as e:
            logger.error(f"❌ 处理最新成交价失败: {e}")    

    def _handle_price_change(self, data: Dict, receive_timestamp: int):
        """处理价格变动更新（非成交、非订单簿）"""
        try:
            market_id = data.get('market')
            price_changes = data.get('price_changes', [])
            server_timestamp = data.get('timestamp')

            if not market_id or not price_changes:
                return

            for pc in price_changes:
                asset_id = pc.get('asset_id')
                price = pc.get('price')
                size = pc.get('size')
                side = pc.get('side')
                best_bid = pc.get('best_bid')
                best_ask = pc.get('best_ask')

                if not asset_id or not price:
                    continue

                price_change = PriceChange(
                    asset_id = asset_id,
                    price = Decimal(price),
                    size = size,
                    side = side,
                    server_timestamp = server_timestamp,
                    receive_timestamp = receive_timestamp,
                    best_bid = Decimal(best_bid),
                    best_ask = Decimal(best_ask)
            )

                # ① 原始 price_change 缓存（用于验证/回放）
                self.price_changes.setdefault(
                    asset_id, deque(maxlen=200)
                ).append(price_change)

                # ② 聚合“最新价格状态”
                self.last_prices[asset_id] = {
                    'price': price,
                    'timestamp': server_timestamp,
                    'source': 'price_change'
                }

                # ③ 聚合最优报价（策略直接用）
                if best_bid and best_ask:
                    self.best_prices[asset_id] = {
                        'bid': Decimal(best_bid),
                        'ask': Decimal(best_ask),
                        'timestamp': server_timestamp
                    }

                # ④ 生成 MarketData（不动 orderbook）
                market_data = self._create_market_data(
                    symbol=asset_id,
                    exchange=ExchangeType.POLYMARKET,
                    last_price=price,
                    external_timestamp=server_timestamp
                )
                if market_data:
                    self._notify_callbacks(market_data)

        except Exception as e:
            logger.error(f"price_change 处理失败: {e}")

    def _update_market_best_prices(self, market_id: str, asset_id: str, best_bid: str, best_ask: str):
        """更新市场最优报价"""
        try:
            # 这里可以更新本地维护的最优买卖价缓存
            # 例如：self.best_prices[market_id][asset_id] = {'bid': best_bid, 'ask': best_ask}
            
            logger.debug(f"更新最优报价: market={market_id}, asset={asset_id}, bid={best_bid}, ask={best_ask}")
            
        except Exception as e:
            logger.error(f"更新最优报价失败: {e}")   

    def _handle_trade(self, data: Dict):
        """处理交易消息 - 更新订单簿和交易历史"""
        try:
            # 解析 Trade 消息的完整结构
            asset_id = data['asset_id']
            trade_id = data['id']
            last_update = int(data['last_update'])
            maker_orders_data = data['maker_orders']
            market = data['market']
            matchtime = int(data['matchtime'])
            outcome = data['outcome']
            owner = data['owner']
            price = Decimal(data['price'])
            side = data['side']  # BUY/SELL
            size = Decimal(data['size'])
            status = data['status']
            taker_order_id = data['taker_order_id']
            timestamp = int(data['timestamp'])
            trade_owner = data['trade_owner']
            msg_type = data['type']
            
            # 创建 MakerOrder 对象列表
            maker_orders = []
            for maker_data in maker_orders_data:
                maker_order = MakerOrder(
                    asset_id=maker_data['asset_id'],
                    matched_amount=float(maker_data['matched_amount']),
                    order_id=maker_data['order_id'],
                    outcome=maker_data['outcome'],
                    owner=maker_data['owner'],
                    price=Decimal(maker_data['price']),
                    receive_timestamp=int(datetime.now(timezone.utc).timestamp() * 1000)
                )
                maker_orders.append(maker_order)
            
            # 创建 Trade 对象
            trade = Trade(
                asset_id=asset_id,
                id=trade_id,
                last_update=last_update,
                maker_orders=maker_orders,
                market=market,
                matchtime=matchtime,
                outcome=outcome,
                owner=owner,
                price=price,
                side=side,
                size=size,
                status=status,
                taker_order_id=taker_order_id,
                trade_owner=trade_owner,
                server_timestamp=timestamp,
                receive_timestamp=int(datetime.now(timezone.utc).timestamp() * 1000)
            )
            
            # 更新订单簿
            if asset_id in self.orderbook_snapshots:
                orderbook = self.orderbook_snapshots[asset_id]
                updated = False
                
                # 根据交易方向和maker_orders更新订单簿
                for maker_order in maker_orders:
                    if side == 'BUY':
                        # taker是买家，maker是卖家，从卖单中移除
                        for ask in orderbook.asks:
                            if ask.price == maker_order.price:
                                # 减少订单数量
                                ask.quantity -= Decimal(str(maker_order.matched_amount))
                                if ask.quantity <= 0:
                                    orderbook.asks.remove(ask)
                                updated = True
                                break
                    else:  # 'SELL'
                        # taker是卖家，maker是买家，从买单中移除
                        for bid in orderbook.bids:
                            if bid.price == maker_order.price:
                                # 减少订单数量
                                bid.quantity -= Decimal(str(maker_order.matched_amount))
                                if bid.quantity <= 0:
                                    orderbook.bids.remove(bid)
                                updated = True
                                break
                
                if updated:
                    orderbook.timestamp = datetime.now(timezone.utc)
                    # 重新排序
                    orderbook.bids.sort(key=lambda x: x.price, reverse=True)
                    orderbook.asks.sort(key=lambda x: x.price)
            
            # 存储交易历史
            if asset_id not in self.trade_history:
                self.trade_history[asset_id] = []
            
            self.trade_history[asset_id].append(trade)
            # 保持最近N笔交易
            if len(self.trade_history[asset_id]) > 1000:
                self.trade_history[asset_id] = self.trade_history[asset_id][-1000:]
            
            # 更新最后成交价
            trade_price_obj = TradeTick(
                trade_id=trade_id,
                symbol=asset_id,
                price=price,
                size=size,
                side=side.lower(),  # 转换为小写以保持一致性
                server_timestamp=datetime.fromtimestamp(timestamp / 1000, tz=timezone.utc),
                receive_timestamp=int(datetime.now(timezone.utc).timestamp() * 1000),
                exchange=ExchangeType.POLYMARKET
            )
            self.last_trade_prices[asset_id] = trade_price_obj
            
            # 生成市场数据
            market_data = self._create_market_data(
                symbol=asset_id,
                exchange=ExchangeType.POLYMARKET,
                last_price=price,
                last_trade=trade_price_obj,
                external_timestamp=datetime.fromtimestamp(timestamp / 1000, tz=timezone.utc)
            )
            
            if market_data:
                self._notify_callbacks(market_data)
                logger.info(f"💹 Trade processed for {asset_id}: {side} {size} @ {price} (status: {status})")
            else:
                logger.warning(f"⚠️ Could not create market data for trade: {asset_id}")
                
        except Exception as e:
            logger.error(f"❌ Error processing trade message: {e}")
            logger.error(f"   Data: {data}")        
            
    def _handle_heartbeat(self, data: Dict):
        """处理心跳消息"""
        # 可以在这里更新连接健康状态
        pass
        
    def _handle_error(self, data: Dict):
        """处理错误消息"""
        error_msg = data.get('message', 'Unknown error')
        logger.error(f"❌ WebSocket error: {error_msg}")

        
    '''
        错误处理接口
    '''            
    def _handle_connection_error(self, st, error: Exception):
        """处理连接错误"""
        logger.error(f"❌ Polymarket WebSocket connection for {st} error: {error}")
        self.is_connected = False

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

    '''
        监控接口
    '''               
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
            "subscribed_markets": list(all_subscribed_markets),  # 汇总所有订阅
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
                "endpoint": self._subscription_config[sub_type].get("endpoint"),
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
            "connection_details": connection_details
        }
    
    '''
        Market接口
    '''
    def _cache_markets(self, markets: List[Dict]):
        """缓存市场核心信息为 CachedMarket 对象"""
        current_time = time.time()
        stats = {
            'new': 0,      # 新缓存
            'updated': 0,  # 更新缓存
            'tokens': 0,   # 新增代币映射
            'failed': 0    # 失败数量
        }
        
        for market in markets:
            market_id = market.get('id')
            if not market_id:
                continue
            
            # 创建 MarketMeta 实例
            try:
                market_meta = MarketMeta.from_api_data(market)
            except Exception as e:
                logger.warning(f"❌ 创建 MarketMeta 失败: {e}, 市场ID: {market_id}")
                stats['failed'] += 1
                continue
            
            # 创建 CachedMarket 对象
            cached_market = CachedMarket(
                meta=market_meta,
                timestamp=current_time
            )
            
            # 检查是否已有缓存
            already_cached = market_id in self.market_cache
            
            # 缓存 CachedMarket
            self.market_cache[market_id] = cached_market
            
            if already_cached:
                stats['updated'] += 1
            else:
                stats['new'] += 1
            
            # 解析并缓存代币ID映射
            token_ids = self._extract_token_ids(market)
            if token_ids:
                for token_id in token_ids:
                    self.token_cache[token_id] = market_id
                    stats['tokens'] += 1
        
        # 记录缓存更新日志
        if stats['new'] > 0 or stats['updated'] > 0:
            logger.info(
                f"🔄 缓存更新: 新增 {stats['new']} 个, 更新 {stats['updated']} 个市场, "
                f"新增 {stats['tokens']} 个代币映射"
            )
        
        if stats['failed'] > 0:
            logger.warning(f"⚠️ 有 {stats['failed']} 个市场缓存失败")

    def _extract_token_ids(self, market: Dict) -> List[str]:
        """从市场信息中提取代币ID"""
        clob_token_ids = market.get('clobTokenIds')
        if not clob_token_ids:
            return []
        
        try:
            # 解析 JSON 字符串
            token_ids = json.loads(clob_token_ids)
            if isinstance(token_ids, list):
                return token_ids
            else:
                logger.warning(f"clobTokenIds 不是列表格式: {type(token_ids)}")
                return []
        except (json.JSONDecodeError, TypeError) as e:
            logger.warning(f"❌ 解析代币ID失败: {e}, 数据: {clob_token_ids[:100] if clob_token_ids else '空'}")
            return []

    def get_cache_stats(self) -> Dict:
        """获取缓存统计信息"""
        total_markets = len(self.market_cache)
        total_tokens = len(self.token_cache)
        
        # 计算过期的缓存数量
        expired_count = 0
        current_time = time.time()
        
        # 注意：我们需要一个单独的时间戳缓存或使用其他机制跟踪过期
        # 由于你提供的结构中没有 cache_timestamps，这里使用一个简化版本
        # 实际实现可能需要添加 cache_timestamps 字典
        
        return {
            'total_markets': total_markets,
            'total_tokens': total_tokens,
            'expired_count': expired_count,
            'cache_hit_rate': 0,  # 需要跟踪命中率时添加
        }        
    
    def get_market_meta(self, market_id: str) -> Optional[MarketMeta]:
        """获取缓存的市场元数据（带TTL检查）"""
        cached = self.market_cache.get(market_id)
        
        if not cached:
            return None
        
        # 检查缓存是否过期
        if cached.is_expired(self.cache_ttl_seconds):
            logger.debug(f"🕒 市场 {market_id} 缓存已过期")
            # 清理过期缓存
            self._cleanup_market_cache(market_id)
            return None
        
        return cached.meta
    
    def _cleanup_market_cache(self, market_id: str):
        """清理指定市场的缓存"""
        # 清理 market_cache
        if market_id in self.market_cache:
            del self.market_cache[market_id]
        
        # 清理 token_cache 中相关的映射
        tokens_to_remove = []
        for token_id, cached_market_id in self.token_cache.items():
            if cached_market_id == market_id:
                tokens_to_remove.append(token_id)
        
        for token_id in tokens_to_remove:
            del self.token_cache[token_id]
        
        logger.debug(f"🧹 清理市场 {market_id} 缓存，移除 {len(tokens_to_remove)} 个代币映射")
    
    def get_market_tokens(self, market_id: str) -> Optional[List[str]]:
        """获取市场对应的所有代币ID"""
        # 从 token_cache 反向查找
        token_ids = []
        for token_id, cached_market_id in self.token_cache.items():
            if cached_market_id == market_id:
                token_ids.append(token_id)
        return token_ids
    
    def get_market_for_token(self, token_id: str) -> Optional[str]:
        """根据代币ID获取所属市场ID"""
        return self.token_cache.get(token_id)
    
    def get_cache_stats(self) -> Dict:
        """获取缓存统计信息"""
        current_time = time.time()
        
        total_markets = len(self.market_cache)
        total_tokens = len(self.token_cache)
        expired_markets = 0
        expired_tokens = 0
        
        # 计算过期的缓存
        for market_id, cached_market in self.market_cache.items():
            if cached_market.is_expired(self.cache_ttl_seconds):
                expired_markets += 1
        
        # 估算过期的代币映射（简化估算）
        if total_markets > 0:
            expired_tokens = int(total_tokens * (expired_markets / total_markets))
        
        # 计算可交易市场数量
        tradable_markets = 0
        for cached_market in self.market_cache.values():
            if not cached_market.is_expired(self.cache_ttl_seconds):
                if cached_market.meta.is_tradable:
                    tradable_markets += 1
        
        return {
            'total_markets': total_markets,
            'valid_markets': total_markets - expired_markets,
            'expired_markets': expired_markets,
            'total_tokens': total_tokens,
            'valid_tokens': total_tokens - expired_tokens,
            'expired_tokens': expired_tokens,
            'tradable_markets': tradable_markets,
        }
        
    async def get_market_list(self, close: Optional[bool] = False, limit: int = 50) -> List[Dict]:
        """获取市场列表 - 支持三种筛选模式，并缓存核心信息"""
        try:
            # 使用封装的 RESTConnector（自动处理代理）
            async with RESTConnector(
                base_url=self.rest_urls[0],
                timeout=10,
                name="polymarket_rest"
            ) as connector:
                
                # 构建查询参数
                params = {
                    "limit": limit,
                    "order": "volumeNum",  # 按交易量排序
                    "ascending": "false",  # 降序排列（交易量大的在前）
                }
                
                # 根据 close 参数决定 closed 参数
                if close is not None:
                    # close 为 True 或 False 时，添加 closed 参数
                    params["closed"] = "true" if close else "false"
                # close 为 None 时不添加 closed 参数，让 API 返回全部
                
                response = await connector.get(
                    "/markets",
                    params=params
                )
                
                if response.status == 200:
                    markets = await response.json()
                    # 🎯 核心修改：缓存市场数据
                    self._cache_markets(markets)

                    # 获取缓存统计
                    cache_stats = self.get_cache_stats()
                    
                    # 统计市场状态（用于日志）
                    active_count = sum(1 for m in markets if m.get('closed') is False)
                    closed_count = sum(1 for m in markets if m.get('closed') is True)
                    
                    # 根据参数确定日志描述
                    if close is None:
                        market_status = "全部（活跃+关闭）"
                    else:
                        market_status = "活跃" if not close else "关闭"
                    
                    # 获取缓存统计
                    cache_stats = self.get_cache_stats()
                    
                    logger.info(
                        f"✅ 成功获取 {len(markets)} 个 {market_status} 市场 "
                        f"(活跃: {active_count}, 关闭: {closed_count}) - "
                        f"缓存: {cache_stats['total_markets']} 个市场, "
                        f"{cache_stats['total_tokens']} 个代币映射"
                    )
                    
                    # 打印前几个市场的详细信息用于调试
                    for i, market in enumerate(markets[:3]):
                        market_id = market.get('id')
                        
                        # 检查是否已在缓存中
                        cached_market = self.market_cache.get(market_id) if market_id else None
                        cache_status = "✅" if cached_market else "❌"
                        
                        closed_flag = "✅" if not market.get('closed') else "❌"
                        logger.info(
                            f"  {closed_flag} 市场 {i+1}: ID={market_id} {cache_status} "
                            f"交易量={market.get('volumeNum')}, "
                            f"问题={market.get('question', '')[:50]}..."
                        )
                        logger.info(f"    结束时间: {market.get('endDate')}")
                        
                        # 显示缓存的信息（如果有）
                        if cached_market:
                            meta = cached_market.meta
                            logger.info(
                                f"    缓存信息: {meta.question[:40]}... "
                                f"订单簿: {meta.enable_order_book}"
                            )
                        
                        if market.get('clobTokenIds'):
                            try:
                                token_ids = json.loads(market['clobTokenIds'])
                                logger.info(f"    Token IDs: {len(token_ids)} 个, 示例: {token_ids[0][:20]}...")
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
        
    async def get_active_market_id(self, limit: int = 5) -> list:
        """获取活跃市场列表"""
        logger.info(f"获取前 {limit} 个活跃市场...")
        try:
            markets = await self.get_active_market(limit)
            
            if not markets:
                logger.warning("无法获取活跃市场列表，使用测试市场ID")
                return None
                
            market_ids = [market['id'] for market in markets if market.get('id')]
            logger.info(f"找到 {len(market_ids)} 个活跃市场: {market_ids}")
            return market_ids
        except Exception as e:
            logger.warning(f"获取市场列表失败: {e}，使用测试市场ID")
            return None
    
    '''
        对外封装接口
    '''
    async def subscribe_orderbook(self, symbols: list):
        """便捷方法：订阅订单簿数据"""
        await self.subscribe(symbols, SubscriptionType.ORDERBOOK)
    
    async def subscribe_trades(self, symbols: list):
        """便捷方法：订阅交易数据"""
        await self.subscribe(symbols, SubscriptionType.TRADE)
    
    async def subscribe_prices(self, symbols: list):
        """便捷方法：订阅价格数据"""
        await self.subscribe(symbols, SubscriptionType.PRICE)    


    def normalize_data(self, raw_data: Dict) -> Optional[MarketData]:
        """标准化数据 - WebSocket版本"""
        # WebSocket版本中，数据已经在_handle_raw_message中处理
        return None            
         