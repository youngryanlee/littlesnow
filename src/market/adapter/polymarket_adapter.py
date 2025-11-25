import asyncio
import logging
from decimal import Decimal
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
import aiohttp
import json

from .base_adapter import BaseAdapter
from ..service.ws_connector import WebSocketConnector
from ..service.rest_connector import RESTConnector
from ..core.data_models import MarketData, OrderBook, OrderBookLevel, ExchangeType, MarketType

logger = logging.getLogger(__name__)

class PolymarketAdapter(BaseAdapter):
    """Polymarket 预测市场适配器"""
    
    def __init__(self):
        super().__init__("polymarket", ExchangeType.POLYMARKET)
        # Polymarket 使用 The Graph 子图作为主要数据源
        self.graphql_url = "https://api.thegraph.com/subgraphs/name/polymarket/matic-mainnet"
        # 备用 REST API
        self.rest_base_url = "https://gamma-api.polymarket.com"
        
        # 市场数据缓存
        self.market_cache: Dict[str, Dict] = {}
        self.condition_cache: Dict[str, Dict] = {}
        
        # 使用服务层的连接器
        self.connector = WebSocketConnector(
            url="",  # Polymarket 暂无官方 WebSocket，暂时为空
            on_message=self._handle_raw_message,
            on_error=self._handle_connection_error,
            ping_interval=30,
            timeout=10,
            name="polymarket"
        )
        
        # 轮询任务
        self._polling_task: Optional[asyncio.Task] = None
        self._polling_interval = 10  # 秒
        
    async def connect(self) -> bool:
        """连接至 Polymarket 数据源"""
        try:
            logger.info("Connecting to Polymarket data sources...")
            
            # 由于 Polymarket 暂无官方 WebSocket，我们使用轮询方式
            # 启动轮询任务
            self._polling_task = asyncio.create_task(self._start_polling())
            
            # 立即检查任务状态，如果任务已经完成且有异常，则抛出
            if self._polling_task.done():
                try:
                    await self._polling_task
                except Exception as e:
                    raise Exception(f"Polling task failed immediately: {e}")
            
            self.is_connected = True
            logger.info("Polymarket adapter connected successfully")
            return True
            
        except Exception as e:
            logger.error(f"Polymarket connection failed: {e}")
            self.is_connected = False
            # 确保清理任务
            if hasattr(self, '_polling_task') and self._polling_task:
                self._polling_task.cancel()
                self._polling_task = None
            return False
            
    async def disconnect(self):
        """断开连接"""
        if self._polling_task:
            self._polling_task.cancel()
            try:
                await self._polling_task
            except asyncio.CancelledError:
                pass
            self._polling_task = None
            
        await self.connector.disconnect()
        self.is_connected = False
        logger.info("Polymarket adapter disconnected")
        
    async def _start_polling(self):
        """启动数据轮询"""
        try:
            while self.is_connected:
                try:
                    await self._poll_market_data()
                    await asyncio.sleep(self._polling_interval)
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.error(f"Error in Polymarket polling: {e}")
                    await asyncio.sleep(self._polling_interval)
        except asyncio.CancelledError:
            logger.info("Polymarket polling task cancelled")
            
    async def _poll_market_data(self):
        """轮询市场数据"""
        if not self.subscribed_symbols:
            return
            
        try:
            # 获取所有订阅市场的当前状态
            for symbol in self.subscribed_symbols:
                market_data = await self._fetch_market_data(symbol)
                if market_data:
                    self._process_market_update(market_data)
                    
        except Exception as e:
            logger.error(f"Error polling Polymarket data: {e}")
            
    async def _fetch_market_data(self, market_id: str) -> Optional[Dict]:
        """获取指定市场的数据"""
        try:
            # 使用 GraphQL 查询市场数据
            query = """
            query GetMarket($id: String!) {
                market(id: $id) {
                    id
                    question
                    outcomes
                    volume
                    liquidity
                    active
                    finalized
                    prices
                    liquidity
                    createdAt
                    condition {
                        id
                        resolutionTimestamp
                    }
                }
            }
            """
            
            variables = {"id": market_id.lower()}
            
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.graphql_url,
                    json={"query": query, "variables": variables},
                    timeout=10
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        return data.get("data", {}).get("market")
                    else:
                        logger.warning(f"Failed to fetch market data for {market_id}: {response.status}")
                        return None
                        
        except Exception as e:
            logger.error(f"Error fetching market data for {market_id}: {e}")
            return None
            
    def _process_market_update(self, market_data: Dict):
        """处理市场数据更新"""
        try:
            if not market_data:
                return
                
            market_id = market_data.get("id")
            if not market_id:
                return
                
            # 创建标准化市场数据
            normalized_data = self.normalize_data(market_data)
            if normalized_data:
                self._notify_callbacks(normalized_data)
                
        except Exception as e:
            logger.error(f"Error processing Polymarket update: {e}")
            
    async def _do_subscribe(self, symbols: List[str]):
        """订阅 Polymarket 市场"""
        logger.info(f"Polymarket subscribing to: {symbols}")
        
        # 验证市场 ID 格式并获取初始数据
        for symbol in symbols:
            try:
                # Polymarket 市场 ID 通常是类似 "0x..." 的地址
                if symbol.startswith("0x") and len(symbol) == 42:
                    market_data = await self._fetch_market_data(symbol)
                    if market_data:
                        self.market_cache[symbol] = market_data
                        # 修复：添加到订阅列表
                        self.subscribed_symbols.add(symbol)
                        logger.info(f"Successfully subscribed to market: {symbol}")
                    else:
                        logger.warning(f"Market not found or inactive: {symbol}")
                else:
                    logger.warning(f"Invalid Polymarket ID format: {symbol}")
                    
            except Exception as e:
                logger.error(f"Error subscribing to {symbol}: {e}")
                
    async def _do_unsubscribe(self, symbols: List[str]):
        """取消订阅"""
        logger.info(f"Polymarket unsubscribing from: {symbols}")
        
        for symbol in symbols:
            if symbol in self.market_cache:
                del self.market_cache[symbol]
            # 修复：从订阅列表中移除
            if symbol in self.subscribed_symbols:
                self.subscribed_symbols.remove(symbol)
                
    def normalize_data(self, raw_data: Dict) -> Optional[MarketData]:
        """标准化 Polymarket 数据为统一的市场数据格式"""
        try:
            market_id = raw_data.get("id")
            if not market_id:
                return None
                
            # 提取关键信息
            question = raw_data.get("question", "Unknown Market")
            outcomes = raw_data.get("outcomes", [])
            prices = raw_data.get("prices", [])
            volume = Decimal(str(raw_data.get("volume", 0)))
            liquidity = Decimal(str(raw_data.get("liquidity", 0)))
            
            # 为预测市场创建特殊的订单簿表示
            # 将不同结果的价格作为"买卖盘"
            orderbook = self._create_prediction_orderbook(outcomes, prices)
            
            # 创建市场数据 - 修复：移除不支持的 additional_info 参数
            market_data = MarketData(
                symbol=market_id,
                exchange=ExchangeType.POLYMARKET,
                market_type=MarketType.PREDICTION,
                timestamp=datetime.now(timezone.utc),
                orderbook=orderbook,
                volume_24h=volume
                # 注意：如果 MarketData 不支持 additional_info，需要移除
            )
            
            logger.debug(f"Normalized Polymarket data for {market_id}")
            return market_data
            
        except Exception as e:
            logger.error(f"Error normalizing Polymarket data: {e}")
            return None
            
    def _create_prediction_orderbook(self, outcomes: List[str], prices: List[float]) -> OrderBook:
        """为预测市场创建订单簿表示"""
        bids = []
        asks = []
        
        try:
            # 将每个结果的价格转换为订单簿档位
            for i, (outcome, price) in enumerate(zip(outcomes, prices)):
                if i >= len(prices):
                    break
                    
                price_decimal = Decimal(str(price))
                
                # 对于预测市场，我们可以将价格视为"买入"该结果的成本
                # 数量可以表示流动性或交易量
                # 修复：移除不支持的 metadata 参数
                bid_level = OrderBookLevel(
                    price=price_decimal,
                    quantity=Decimal("1.0")  # 标准化数量
                )
                bids.append(bid_level)
                
                # 卖盘可以表示卖出/做空该结果
                ask_level = OrderBookLevel(
                    price=Decimal("1.0") - price_decimal,  # 互补价格
                    quantity=Decimal("1.0")
                )
                asks.append(ask_level)
                
        except Exception as e:
            logger.error(f"Error creating prediction orderbook: {e}")
            
        return OrderBook(
            bids=bids,
            asks=asks,
            timestamp=datetime.now(timezone.utc),
            symbol="prediction_market"
        )
        
    def _handle_raw_message(self, raw_data: Dict):
        """处理原始消息（预留用于未来的 WebSocket 支持）"""
        # Polymarket 暂无官方 WebSocket，此方法预留
        logger.debug(f"Raw message received: {raw_data}")
        
    def _handle_connection_error(self, error: Exception):
        """处理连接错误"""
        logger.error(f"Polymarket connection error: {error}")
        self.is_connected = False
        
        # 触发重连逻辑
        asyncio.create_task(self._attempt_reconnect())
        
    async def _attempt_reconnect(self):
        """尝试重新连接"""
        logger.info("Attempting to reconnect to Polymarket...")
        await asyncio.sleep(5)
        
        try:
            success = await self.connect()
            if success and self.subscribed_symbols:
                await self.subscribe(list(self.subscribed_symbols))
        except Exception as e:
            logger.error(f"Polymarket reconnection attempt failed: {e}")
            
    def get_connection_status(self) -> Dict:
        """获取连接状态信息"""
        # 修复：直接实现，不调用基类方法
        polling_status = "active" if self._polling_task and not self._polling_task.done() else "inactive"
        
        return {
            "name": self.name,
            "exchange": self.exchange_type.value,
            "is_connected": self.is_connected,
            "subscribed_symbols": list(self.subscribed_symbols),
            "callback_count": len(self.callbacks),
            "polling_status": polling_status,
            "subscribed_markets": list(self.subscribed_symbols),
            "cached_markets": len(self.market_cache),
            "polling_interval": self._polling_interval
        }
        
    async def get_market_list(self, limit: int = 50) -> List[Dict]:
        """获取可用市场列表"""
        try:
            query = """
            query GetMarkets($first: Int!) {
                markets(first: $first, orderBy: volume, orderDirection: desc) {
                    id
                    question
                    outcomes
                    volume
                    liquidity
                    active
                    finalized
                    prices
                    createdAt
                }
            }
            """
            
            variables = {"first": limit}
            
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.graphql_url,
                    json={"query": query, "variables": variables},
                    timeout=10
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        return data.get("data", {}).get("markets", [])
                    else:
                        logger.error(f"Failed to fetch market list: {response.status}")
                        return []
                        
        except Exception as e:
            logger.error(f"Error fetching market list: {e}")
            return []