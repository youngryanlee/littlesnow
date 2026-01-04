from abc import abstractmethod
from typing import Optional, Union
from decimal import Decimal
from datetime import datetime, timezone

from .adapter_interface import BaseMarketAdapter
from ..core.data_models import MarketData, ExchangeType
from ..core.data_models import MarketData, OrderBook, ExchangeType, MarketType, TradeTick
from logger.logger import get_logger

logger = get_logger()

class BaseAdapter(BaseMarketAdapter):
    """适配器基类实现"""
    
    def __init__(self, name: str, exchange_type: ExchangeType):
        super().__init__(name)
        self.exchange_type = exchange_type
        self.subscribed_symbols = set()
        
    async def subscribe(self, symbols: list):
        """订阅交易对"""
        new_symbols = set(symbols) - self.subscribed_symbols
        if new_symbols:
            await self._do_subscribe(list(new_symbols))
            self.subscribed_symbols.update(new_symbols)
            
    async def unsubscribe(self, symbols: list):
        """取消订阅"""
        to_remove = set(symbols) & self.subscribed_symbols
        if to_remove:
            await self._do_unsubscribe(list(to_remove))
            self.subscribed_symbols -= to_remove
            
    @abstractmethod
    async def _do_subscribe(self, symbols: list):
        """实际执行订阅逻辑"""
        pass
        
    @abstractmethod 
    async def _do_unsubscribe(self, symbols: list):
        """实际执行取消订阅逻辑"""
        pass
    
    def _create_market_data(
        self,
        symbol: str,
        exchange: ExchangeType,
        market_type: Optional[MarketType] = MarketType.PREDICTION,
        orderbook: Optional[OrderBook] = None,
        last_price: Optional[Union[str, Decimal]] = None,
        last_trade: Optional[TradeTick] = None,
        external_timestamp: Optional[datetime] = None
    ) -> Optional[MarketData]:
        """
        创建市场数据对象。
        若无快照，则返回None。
        传入last_price等新参数:
            即使没有订单簿快照，也可利用新参数创建基础MarketData。
        """
        try:
            # 1. 确定时间戳：优先使用外部传入的，否则用当前时间
            timestamp = external_timestamp or datetime.now(timezone.utc)
            
            # 2. 🎯 核心逻辑：判断调用模式
            # 情况A：传统调用，无新参数 -> 严格要求必须有订单簿
            if last_price is None and last_trade is None:
                if not orderbook:
                    # 维持原有行为：无订单簿则返回None
                    return None
                # 有订单簿，创建传统订单簿数据
                return MarketData(
                    symbol=symbol,
                    exchange=exchange,
                    market_type=market_type,
                    timestamp=timestamp,
                    orderbook=orderbook,
                    # last_price 和 last_trade 默认为 None
                )
            
            # 情况B：增强调用，传入了新参数 -> 允许创建不依赖订单簿的数据
            # 处理价格
            final_last_price = None
            if last_price is not None:
                final_last_price = Decimal(str(last_price))
            
            # 创建MarketData
            return MarketData(
                symbol=symbol,
                exchange=exchange,
                market_type=market_type,
                timestamp=timestamp,
                orderbook=orderbook,           # 有则附带，无则None
                last_price=final_last_price,   # 来自新参数
                last_trade=last_trade          # 来自新参数
            )
            
        except Exception as e:
            logger.error(f"❌ Error creating market data: {e}")
            return None