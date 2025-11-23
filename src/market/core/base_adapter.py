from abc import ABC, abstractmethod
from typing import List, Callable, Optional
import asyncio
import logging
from .data_models import MarketData

logger = logging.getLogger(__name__)

class BaseMarketAdapter(ABC):
    """市场数据适配器基类"""
    
    def __init__(self, name: str):
        self.name = name
        self.is_connected = False
        self._callbacks: List[Callable[[MarketData], None]] = []
        
    @abstractmethod
    async def connect(self) -> bool:
        """连接到数据源"""
        pass
        
    @abstractmethod
    async def disconnect(self):
        """断开连接"""
        pass
        
    @abstractmethod
    async def subscribe(self, symbols: List[str]):
        """订阅交易对"""
        pass
        
    @abstractmethod
    async def unsubscribe(self, symbols: List[str]):
        """取消订阅"""
        pass
        
    def add_callback(self, callback: Callable[[MarketData], None]):
        """添加数据回调"""
        self._callbacks.append(callback)
        
    def remove_callback(self, callback: Callable[[MarketData], None]):
        """移除数据回调"""
        if callback in self._callbacks:
            self._callbacks.remove(callback)
            
    def _notify_callbacks(self, data: MarketData):
        """通知所有回调函数"""
        for callback in self._callbacks:
            try:
                callback(data)
            except Exception as e:
                logger.error(f"Callback error in {self.name}: {e}")
                
    @abstractmethod
    def normalize_data(self, raw_data: dict) -> Optional[MarketData]:
        """标准化原始数据"""
        pass