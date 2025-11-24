from abc import abstractmethod
from .adapter_interface import BaseMarketAdapter
from ..core.data_models import MarketData, ExchangeType

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