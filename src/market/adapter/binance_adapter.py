import asyncio
import logging
from decimal import Decimal
from datetime import datetime, timezone
from typing import Optional, List, Dict
import aiohttp
import json

from .base_adapter import BaseAdapter
from ..service.ws_connector import WebSocketConnector
from ..service.rest_connector import RESTConnector 
from ..core.data_models import MarketData, OrderBook, OrderBookLevel, ExchangeType, MarketType

logger = logging.getLogger(__name__)

class BinanceAdapter(BaseAdapter):
    """Binance 交易所适配器 - 带降级方案的完整流程"""
    
    def __init__(self):
        super().__init__("binance", ExchangeType.BINANCE)
        self.ws_url = "wss://stream.binance.com:9443/ws"
        self.rest_base_url = "https://api.binance.com/api/v3"
        
        # 订单簿状态管理
        self.orderbook_snapshots: Dict[str, OrderBook] = {}
        self.last_update_ids: Dict[str, int] = {}
        self.pending_updates: Dict[str, List[dict]] = {}
        self.snapshot_initialized: Dict[str, bool] = {}
        self.using_fallback: Dict[str, bool] = {}
        
        # 使用服务层的连接器
        self.connector = WebSocketConnector(
            url=self.ws_url,
            on_message=self._handle_raw_message,
            on_error=self._handle_connection_error,
            ping_interval=30,
            timeout=10,
            name="binance"
        )
        
    async def initialize_snapshot(self, symbol: str) -> bool:
        """通过 REST API 初始化订单簿快照 - 使用 RESTConnector"""
        max_retries = 2
        for attempt in range(max_retries):
            try:
                logger.info(f"🔍 初始化 {symbol} 订单簿快照 (尝试 {attempt + 1}/{max_retries})...")
                
                # 使用 RESTConnector
                async with RESTConnector(
                    base_url=self.rest_base_url,
                    timeout=15,
                    name=f"binance_{symbol}"
                ) as rest:
                    snapshot = await rest.get_json(f"/depth?symbol={symbol}&limit=100")
                    last_update_id = snapshot['lastUpdateId']
                    
                    logger.info(f"🔍 收到 {symbol} 快照，最后更新ID: {last_update_id}")
                    
                    # 解析快照数据
                    bids = [
                        OrderBookLevel(
                            price=Decimal(level[0]),
                            quantity=Decimal(level[1])
                        ) for level in snapshot['bids']
                    ]
                    
                    asks = [
                        OrderBookLevel(
                            price=Decimal(level[0]),
                            quantity=Decimal(level[1])
                        ) for level in snapshot['asks']
                    ]
                    
                    # 排序
                    bids.sort(key=lambda x: x.price, reverse=True)
                    asks.sort(key=lambda x: x.price)
                    
                    # 限制深度
                    bids = bids[:20]
                    asks = asks[:20]
                    
                    # 创建订单簿快照
                    orderbook = OrderBook(
                        bids=bids,
                        asks=asks,
                        timestamp=datetime.now(timezone.utc),
                        symbol=symbol
                    )
                    
                    self.orderbook_snapshots[symbol] = orderbook
                    self.last_update_ids[symbol] = last_update_id
                    self.snapshot_initialized[symbol] = True
                    self.pending_updates[symbol] = []
                    self.using_fallback[symbol] = False
                    
                    logger.info(f"✅ {symbol} 订单簿快照初始化完成: 买单{len(bids)}档, 卖单{len(asks)}档")
                    return True
                        
            except asyncio.TimeoutError:
                logger.warning(f"⚠️ 获取 {symbol} 快照超时 (尝试 {attempt + 1}/{max_retries})")
                if attempt < max_retries - 1:
                    await asyncio.sleep(1)
                continue
            except Exception as e:
                logger.warning(f"⚠️ 初始化 {symbol} 订单簿失败 (尝试 {attempt + 1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(1)
                continue
        
        logger.error(f"❌ {symbol} 订单簿快照初始化完全失败，将使用降级方案")
        return False

    def _initialize_from_first_update(self, symbol: str, first_update: dict):
        """从第一个增量更新初始化订单簿（降级方案）"""
        try:
            logger.info(f"🔍 使用降级方案从第一个更新初始化 {symbol} 订单簿")
            
            # 从第一个更新中提取有效的买单和卖单
            bids = []
            for price_str, quantity_str in first_update.get('b', []):
                quantity = Decimal(quantity_str)
                if quantity > 0:
                    bids.append(OrderBookLevel(
                        price=Decimal(price_str),
                        quantity=quantity
                    ))
            
            asks = []
            for price_str, quantity_str in first_update.get('a', []):
                quantity = Decimal(quantity_str)
                if quantity > 0:
                    asks.append(OrderBookLevel(
                        price=Decimal(price_str),
                        quantity=quantity
                    ))
            
            # 排序
            bids.sort(key=lambda x: x.price, reverse=True)
            asks.sort(key=lambda x: x.price)
            
            # 限制深度
            bids = bids[:20]
            asks = asks[:20]
            
            # 创建订单簿
            if 'E' in first_update:
                timestamp = datetime.fromtimestamp(first_update['E'] / 1000, tz=timezone.utc)
            else:
                timestamp = datetime.now(timezone.utc)
                
            orderbook = OrderBook(
                bids=bids,
                asks=asks,
                timestamp=timestamp,
                symbol=symbol
            )
            
            self.orderbook_snapshots[symbol] = orderbook
            self.last_update_ids[symbol] = first_update.get('u')
            self.snapshot_initialized[symbol] = True
            self.using_fallback[symbol] = True
            
            logger.info(f"✅ 降级方案初始化 {symbol} 订单簿完成: 买单{len(bids)}档, 卖单{len(asks)}档")
            
        except Exception as e:
            logger.error(f"❌ 降级方案初始化失败: {e}")
    
    def _handle_outdated_snapshot(self, symbol: str, update_data: dict):
        """处理过时的快照 - 使用WebSocket更新重新初始化"""
        try:
            logger.debug(f"🔄 {symbol} 检测到快照过时，使用WebSocket更新重新初始化")
            
            # 使用当前更新数据重新初始化
            self._initialize_from_first_update(symbol, update_data)
            
            # 标记为使用降级方案
            self.using_fallback[symbol] = True
            
            logger.debug(f"✅ {symbol} 已使用WebSocket更新重新初始化")
            
        except Exception as e:
            logger.error(f"❌ 重新初始化 {symbol} 失败: {e}")
            # 如果重新初始化失败，尝试重新获取快照
            asyncio.create_task(self._retry_snapshot_initialization(symbol))

    async def _retry_snapshot_initialization(self, symbol: str):
        """重新尝试初始化快照"""
        try:
            logger.debug(f"🔄 重新尝试获取 {symbol} 快照...")
            success = await self.initialize_snapshot(symbol)
            if success:
                logger.debug(f"✅ {symbol} 快照重新初始化成功")
                # 重置降级方案标志
                self.using_fallback[symbol] = False
                # 清空缓存更新，因为快照已经是最新的
                if symbol in self.pending_updates:
                    self.pending_updates[symbol] = []
            else:
                logger.debug(f"❌ {symbol} 快照重新初始化失败，继续使用降级方案")
        except Exception as e:
            logger.error(f"❌ 重新初始化 {symbol} 快照时出错: {e}")
            
    async def connect(self) -> bool:
        """连接至 Binance WebSocket"""
        try:
            success = await self.connector.connect()
            self.is_connected = success
            return success
        except Exception as e:
            logger.error(f"Binance connection failed: {e}")
            self.is_connected = False
            return False
            
    async def disconnect(self):
        """断开连接"""
        await self.connector.disconnect()
        self.is_connected = False
        
    async def _do_subscribe(self, symbols: List[str]):
        """订阅 Binance 交易对"""
        if not self.is_connected:
            logger.warning("Not connected to Binance")
            return
            
        streams = []
        for symbol in symbols:
            symbol_lower = symbol.lower()
            streams.extend([
                f"{symbol_lower}@depth@100ms",
                f"{symbol_lower}@trade"
            ])
            
            # 为每个交易对初始化快照
            if symbol not in self.snapshot_initialized:
                success = await self.initialize_snapshot(symbol)
                if not success:
                    logger.warning(f"⚠️ {symbol} 快照初始化失败，将使用第一个WebSocket更新初始化")
                    # 创建空的订单簿作为占位符，等待第一个更新
                    self.orderbook_snapshots[symbol] = OrderBook(
                        bids=[], asks=[], 
                        timestamp=datetime.now(timezone.utc),
                        symbol=symbol
                    )
                    self.snapshot_initialized[symbol] = False
                    self.pending_updates[symbol] = []
                    self.using_fallback[symbol] = False
            
        subscribe_msg = {
            "method": "SUBSCRIBE",
            "params": streams,
            "id": 1
        }
        
        await self.connector.send_json(subscribe_msg)
        logger.info(f"Subscribed to {symbols} on Binance")
        
    async def _do_unsubscribe(self, symbols: List[str]):
        """取消订阅"""
        if not self.is_connected:
            return
            
        streams = []
        for symbol in symbols:
            symbol_lower = symbol.lower()
            streams.extend([
                f"{symbol_lower}@depth@100ms", 
                f"{symbol_lower}@trade"
            ])
            
        unsubscribe_msg = {
            "method": "UNSUBSCRIBE",
            "params": streams,
            "id": 1
        }
        
        await self.connector.send_json(unsubscribe_msg)
        logger.info(f"Unsubscribed from {symbols} on Binance")
        
    def _handle_raw_message(self, raw_data: dict):
        """处理原始 WebSocket 消息"""
        try:
            # print("_handle_raw_message: ", raw_data)
            if 'stream' in raw_data:  
                stream = raw_data['stream']
                if '@depth' in stream:
                    self._handle_orderbook_update(raw_data)
                elif '@trade' in stream:
                    self._handle_trade(raw_data)
                else:
                    logger.error(f"Error handling raw message: {raw_data}")       
            elif 'e' in raw_data:  
                event_type = raw_data['e']
                if event_type == 'depthUpdate': 
                    self._handle_orderbook_update(raw_data)
                elif event_type == 'trade':  
                    self._handle_trade(raw_data)
                else:
                    logger.error(f"Error handling raw message: {raw_data}")   
            else:
                logger.error(f"Error handling raw message: {raw_data}")   
                    
        except Exception as e:
            logger.error(f"Error handling raw message: {e}")
            import traceback
            traceback.print_exc()
            
    def _handle_orderbook_update(self, data: dict):
        """处理订单簿增量更新"""
        try:
            # 提取数据
            if 'stream' in data:
                symbol = data['stream'].split('@')[0].upper()
                update_data = data['data']
            else:
                symbol = data['s']
                update_data = data
            
            logger.debug(f"🔍 开始处理 {symbol} 订单簿更新")
            
            # 如果快照未初始化，使用第一个更新来初始化（降级方案）
            if not self.snapshot_initialized.get(symbol, False):
                logger.info(f"🔍 {symbol} 使用第一个WebSocket更新初始化订单簿")
                self._initialize_from_first_update(symbol, update_data)
                return
            
            current_U = update_data.get('U')
            current_u = update_data.get('u')
            last_update_id = self.last_update_ids.get(symbol)
            
            logger.debug(f"🔍 {symbol} 增量更新: U={current_U}, u={current_u}, 最后ID={last_update_id}")
            
            # 如果使用降级方案，直接应用所有更新
            if self.using_fallback.get(symbol, False):
                logger.debug(f"🔍 {symbol} 使用降级方案处理更新")
                self._apply_orderbook_update(symbol, update_data)
                self.last_update_ids[symbol] = current_u
                return
            
            # 官方流程：丢弃任何 u <= lastUpdateId 的数据
            if last_update_id is not None and current_u <= last_update_id:
                logger.debug(f"🔍 丢弃旧更新: u={current_u} <= lastUpdateId={last_update_id}")
                return
            
            # 官方流程：如果 U <= lastUpdateId+1 且 u >= lastUpdateId+1，开始处理
            if last_update_id is not None:
                expected_U = last_update_id + 1
                if current_U <= expected_U <= current_u:
                    # 符合条件，处理此更新
                    logger.debug(f"📥 处理更新 {symbol}: U={current_U}, u={current_u}, 期望 U={expected_U}")
                    self._apply_orderbook_update(symbol, update_data)
                    self.last_update_ids[symbol] = current_u
                    
                    # 处理之前缓存的更新
                    self._process_pending_updates(symbol)
                elif current_U > expected_U:
                    # 关键修复：如果 U 远大于期望值，说明快照已过时，需要重新初始化
                    logger.debug(f"⚠️ {symbol} 快照已过时 (U={current_U} > 期望={expected_U})，重新初始化快照")
                    self._handle_outdated_snapshot(symbol, update_data)
                else:
                    # 不符合条件，缓存此更新
                    print(f"📥 缓存更新 {symbol}: U={current_U}, u={current_u}, 期望 U={expected_U}")
                    if symbol not in self.pending_updates:
                        self.pending_updates[symbol] = []
                    self.pending_updates[symbol].append(update_data)
            else:
                # 没有 lastUpdateId，直接应用更新
                logger.debug(f"⚠️ {symbol} 没有 lastUpdateId，直接应用更新")
                self._apply_orderbook_update(symbol, update_data)
                self.last_update_ids[symbol] = current_u
            
        except Exception as e:
            logger.error(f"Error processing Binance orderbook update: {e}")
            import traceback
            traceback.print_exc()
    
    def _process_pending_updates(self, symbol: str):
        """处理缓存的增量更新"""
        if symbol not in self.pending_updates or not self.pending_updates[symbol]:
            return
        
        pending_updates = self.pending_updates[symbol]
        last_update_id = self.last_update_ids[symbol]
        
        logger.info(f"🔍 开始处理 {symbol} 的 {len(pending_updates)} 个缓存更新")
        
        # 按顺序处理缓存更新
        processed_count = 0
        for update_data in pending_updates[:]:
            current_U = update_data.get('U')
            current_u = update_data.get('u')
            
            if current_U == last_update_id + 1:
                # 符合条件，处理此更新
                self._apply_orderbook_update(symbol, update_data)
                self.last_update_ids[symbol] = current_u
                last_update_id = current_u
                pending_updates.remove(update_data)
                processed_count += 1
                logger.debug(f"  ✅ 处理缓存更新: U={current_U}, u={current_u}")
            else:
                # 不再符合条件，停止处理
                break
        
        logger.info(f"✅ 处理了 {symbol} 的 {processed_count} 个缓存更新，剩余 {len(pending_updates)} 个")
    
    def _apply_orderbook_update(self, symbol: str, update_data: dict):
        """应用订单簿增量更新到快照"""
        try:
            current_orderbook = self.orderbook_snapshots[symbol]
            
            # 创建新的 bids 和 asks 列表
            new_bids = current_orderbook.bids.copy() if current_orderbook.bids else []
            new_asks = current_orderbook.asks.copy() if current_orderbook.asks else []
            
            # 处理买单更新
            bids_update = update_data.get('b', [])
            for price_str, quantity_str in bids_update:
                price = Decimal(price_str)
                quantity = Decimal(quantity_str)
                
                # 移除现有的该价格档位
                new_bids = [bid for bid in new_bids if bid.price != price]
                
                # 如果数量大于0，添加新的档位
                if quantity > 0:
                    new_bid = OrderBookLevel(price=price, quantity=quantity)
                    new_bids.append(new_bid)
            
            # 处理卖单更新
            asks_update = update_data.get('a', [])
            for price_str, quantity_str in asks_update:
                price = Decimal(price_str)
                quantity = Decimal(quantity_str)
                
                # 移除现有的该价格档位
                new_asks = [ask for ask in new_asks if ask.price != price]
                
                # 如果数量大于0，添加新的档位
                if quantity > 0:
                    new_ask = OrderBookLevel(price=price, quantity=quantity)
                    new_asks.append(new_ask)
            
            # 排序
            new_bids.sort(key=lambda x: x.price, reverse=True)
            new_asks.sort(key=lambda x: x.price)
            
            # 限制深度
            new_bids = new_bids[:20]
            new_asks = new_asks[:20]
            
            # 创建新的 OrderBook 实例
            if 'E' in update_data:
                timestamp = datetime.fromtimestamp(update_data['E'] / 1000, tz=timezone.utc)
            else:
                timestamp = datetime.now(timezone.utc)
                
            updated_orderbook = OrderBook(
                bids=new_bids,
                asks=new_asks,
                timestamp=timestamp,
                symbol=symbol
            )
            
            # 更新快照
            self.orderbook_snapshots[symbol] = updated_orderbook
            
            # 生成市场数据
            market_data = MarketData(
                symbol=symbol,
                exchange=ExchangeType.BINANCE,
                market_type=MarketType.SPOT,
                timestamp=datetime.now(timezone.utc),
                orderbook=updated_orderbook
            )
            
            logger.debug(f"✅ {symbol} 订单簿更新: 买单{len(new_bids)}档, 卖单{len(new_asks)}档")
            if new_bids and new_asks:
                logger.debug(f"   最佳买单: {new_bids[0].price} x {new_bids[0].quantity}")
                logger.debug(f"   最佳卖单: {new_asks[0].price} x {new_asks[0].quantity}")
            
            self._notify_callbacks(market_data)
            
        except Exception as e:
            logger.error(f"❌ 应用订单簿更新失败: {e}")
            raise
            
    def _handle_trade(self, data: dict):
        """处理交易数据"""
        try:
            logger.debug(f"Trade data received: {data}")
        except Exception as e:
            logger.error(f"Error processing Binance trade: {e}")
            
    def _handle_connection_error(self, error: Exception):
        """处理连接错误"""
        logger.error(f"Binance WebSocket connection error: {error}")
        self.is_connected = False
        
        # 触发重连逻辑
        asyncio.create_task(self._attempt_reconnect())
        
    async def _attempt_reconnect(self):
        """尝试重新连接"""
        logger.info("Attempting to reconnect to Binance...")
        await asyncio.sleep(5)
        
        try:
            success = await self.connect()
            if success and self.subscribed_symbols:
                await self.subscribe(list(self.subscribed_symbols))
        except Exception as e:
            logger.error(f"Reconnection attempt failed: {e}")
            
    def normalize_data(self, raw_data: dict) -> Optional[MarketData]:
        """标准化数据"""
        return None
        
    def get_connection_status(self) -> dict:
        """获取连接状态信息"""
        base_status = super().get_connection_status()
        connector_info = self.connector.get_connection_info()
        
        return {
            **base_status,
            "connector_info": connector_info,
            "subscribed_symbols": list(self.subscribed_symbols),
            "snapshot_initialized": self.snapshot_initialized.copy(),
            "using_fallback": self.using_fallback.copy()
        }
    