from abc import abstractmethod
from typing import Optional, Union
from decimal import Decimal
from datetime import datetime, timezone
from typing import Optional, Dict

from .adapter_interface import BaseMarketAdapter
from ..core.data_models import MarketData, ExchangeType
from ..core.data_models import MarketData, OrderBook, ExchangeType, MarketType, TradeTick
from ..monitor.collector import MarketMonitor
from logger.logger import get_logger

logger = get_logger()

class BaseAdapter(BaseMarketAdapter):
    """适配器基类实现"""
    
    def __init__(self, name: str, exchange_type: ExchangeType):
        super().__init__(name)
        self.exchange_type = exchange_type
        self.subscribed_symbols = set()
        self.monitor = None  # 将稍后设置
        
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
        
    def set_monitor(self, monitor: MarketMonitor):
        """设置监控器"""
        self.monitor = monitor
        if self.monitor:
            self.monitor.register_adapter(
                adapter_name=self.name,
                exchange_type=self.exchange_type,
            )  

    def update_basic_stats(self, latency_ms: Optional[float] = None):
        """更新基础统计指标"""
        if not hasattr(self, 'monitor') or not self.monitor:
            return
            
        try:
            metrics = self.monitor.get_metrics(self.name)
            
            # 更新接收和处理计数
            metrics.data.messages_received += 1
            metrics.data.messages_processed += 1

            # 更新订阅列表（如果适配器有这个属性）
            if hasattr(self, 'subscribed_symbols'):
                metrics.data.subscribed_symbols = self.subscribed_symbols.copy()
            
            # 更新延迟
            self._record_latency(latency_ms)
                      
        except Exception as e:
            logger.exception(f"更新基础统计失败: {e}")          
    
    def _record_base_metrics(self, latency_ms: float = None, 
                           processing_ms: float = None,
                           is_connected: bool = None):
        """记录基础指标"""
        if not self.monitor:
            return
        
        if latency_ms is not None:
            self.monitor.record_latency(self.name, latency_ms)
        
        if processing_ms is not None:
            self.monitor.record_processing_time(self.name, processing_ms)
        
        if is_connected is not None:
            self.monitor.record_connection_status(self.name, is_connected)
    
    def _record_verification_result(self, symbol: str, is_valid: bool, details: Dict):
        """触发验证结果记录（内部方法）"""
        if self.monitor:
            self.monitor.record_validation_result(
                adapter_name=self.name,
                symbol=symbol,
                is_valid=is_valid,
                details=details
            )
    
    def _record_latency(self, latency_ms: float):
        """触发延迟记录（内部方法）"""
        if self.monitor:
            self.monitor.record_latency(
                adapter_name=self.name,
                latency_ms=latency_ms
            )
    
    def _record_connection_event(self, is_connected: bool):
        """触发连接事件记录"""
        if self.monitor:
            self.monitor.record_connection_status(
                adapter_name=self.name,
                is_connected=is_connected
            )    