import asyncio
import logging
from decimal import Decimal
from datetime import datetime, timezone
from typing import Optional, List

from .base import BaseAdapter
from ..service.ws_connector import WebSocketConnector  # 更新导入路径
from ..core.data_models import MarketData, OrderBook, OrderBookLevel, ExchangeType, MarketType

logger = logging.getLogger(__name__)

class BinanceAdapter(BaseAdapter):
    """Binance 交易所适配器 - 使用服务层的 WebSocket 连接器"""
    
    def __init__(self):
        super().__init__("binance", ExchangeType.BINANCE)
        self.ws_url = "wss://stream.binance.com:9443/ws"
        
        # 使用服务层的 WebSocket 连接器
        self.connector = WebSocketConnector(
            url=self.ws_url,
            on_message=self._handle_raw_message,
            on_error=self._handle_connection_error,
            ping_interval=30,
            timeout=10,
            name="binance"  # 标识这个连接器
        )
        
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
            logger.info(f"🔍 收到原始消息: {raw_data}")  # 添加这行
            
            if 'stream' in raw_data:
                stream = raw_data['stream']
                logger.info(f"🔍 处理stream格式: {stream}")
                if '@depth' in stream:
                    self._handle_orderbook(raw_data)
                elif '@trade' in stream:
                    self._handle_trade(raw_data)
                else:
                    logger.info(f"❓ 未知的stream类型: {stream}")
            elif 'e' in raw_data:
                event_type = raw_data['e']
                logger.info(f"🔍 处理事件格式: {event_type}")
                if event_type == 'depthUpdate':
                    self._handle_orderbook(raw_data)
                elif event_type == 'trade':
                    self._handle_trade(raw_data)
                else:
                    logger.info(f"❓ 未知的事件类型: {event_type}")
            else:
                logger.info(f"❓ 无法识别的消息格式: {raw_data}")
                
        except Exception as e:
            logger.error(f"Error handling raw message: {e}")
            import traceback
            traceback.print_exc()  # 添加详细堆栈跟踪
            
    def _handle_orderbook(self, data: dict):
        """处理订单簿数据 - 简化版本，只处理当前更新"""
        try:
            if 'stream' in data:
                symbol = data['stream'].split('@')[0].upper()
                orderbook_data = data['data']
            else:
                symbol = data['s']
                orderbook_data = data
            
            # 只解析当前更新中的有效档位（数量>0的）
            bids = []
            for level in orderbook_data.get('b', []):
                price_str, quantity_str = level
                quantity = Decimal(quantity_str)
                if quantity > 0:  # 只处理数量大于0的档位
                    bids.append(OrderBookLevel(
                        price=Decimal(price_str),
                        quantity=quantity
                    ))
            
            asks = []
            for level in orderbook_data.get('a', []):
                price_str, quantity_str = level
                quantity = Decimal(quantity_str)
                if quantity > 0:  # 只处理数量大于0的档位
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
            if 'E' in orderbook_data:
                timestamp = datetime.fromtimestamp(orderbook_data['E'] / 1000, tz=timezone.utc)
            else:
                timestamp = datetime.now(timezone.utc)
                
            orderbook = OrderBook(
                bids=bids,
                asks=asks,
                timestamp=timestamp,
                symbol=symbol
            )
            
            market_data = MarketData(
                symbol=symbol,
                exchange=ExchangeType.BINANCE,
                market_type=MarketType.SPOT,
                timestamp=datetime.now(timezone.utc),
                orderbook=orderbook
            )
            
            logger.info(f"订单簿更新: {symbol} - 买单{len(bids)}档, 卖单{len(asks)}档")
            self._notify_callbacks(market_data)
            
        except Exception as e:
            logger.error(f"Error processing Binance orderbook: {e}")
            import traceback
            traceback.print_exc()
            
    def _handle_trade(self, data: dict):
        """处理交易数据"""
        try:
            logger.debug(f"Trade data received: {data}")
            # 交易数据处理逻辑可以在这里实现
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
            "subscribed_symbols": list(self.subscribed_symbols)
        }