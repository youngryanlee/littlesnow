from abc import abstractmethod
from typing import Optional, Union
from decimal import Decimal
from datetime import datetime, timezone
from typing import Optional, Dict

from .adapter_interface import BaseMarketAdapter
from ..core.data_models import MarketData, ExchangeType
from ..core.data_models import MarketData, OrderBook, ExchangeType, MarketType, TradeTick
from ..monitor.collector import MarketMonitor
from ..utils.time_sync import TimeSyncManager

from logger.logger import get_logger

logger = get_logger()

class BaseAdapter(BaseMarketAdapter):
    """适配器基类实现"""
    
    def __init__(self, name: str, exchange_type: ExchangeType):
        super().__init__(name)
        self.exchange_type = exchange_type
        self.subscribed_symbols = set()
        self.monitor = None  # 将稍后设置

        # 创建时间同步管理器
        self.time_sync = TimeSyncManager(
            adapter_name=name,       # 适配器名称（用于日志）
            window_size=100          # 滑动窗口大小（默认100）
        )
        
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
        
    def _update_monitor_stats(self, message_type: str, server_timestamp_ms: int, received_timestamp_ms: int):

        latency_ms = received_timestamp_ms - server_timestamp_ms
        # 记录异常情况，但不修正数据
        if latency_ms < 0:
            #logger.(f"{message_type} 负延迟: {latency_ms}ms (服务器时间可能比本地晚), server_timestamp_ms={server_timestamp_ms}, received_timestamp_ms={received_timestamp_ms}")
            # 使用TimeSyncManager校正延迟
            latency_ms = self.time_sync.update_offset(
                server_timestamp_ms=server_timestamp_ms,
                received_timestamp_ms=received_timestamp_ms
            )
            #logger.info(f"{message_type} 校准延迟: {latency_ms}ms")
            
        elif latency_ms > 10000:  # 10秒
            logger.warning(f"{message_type} 高延迟: {latency_ms}ms (可能网络有问题), server_timestamp_ms={server_timestamp_ms}, received_timestamp_ms={received_timestamp_ms}")

        """ 更新统计 """
        try:
            """更新基础统计"""
            self.update_basic_stats(message_type, latency_ms)
            
        except Exception as e:
            logger.exception(f"更新延迟统计失败: {e}")        

    def update_basic_stats(self, message_type: str, latency_ms: Optional[float] = None):
        """更新基础统计指标"""
        if not hasattr(self, 'monitor') or not self.monitor:
            return
            
        try:
            metrics = self.monitor.get_metrics(self.name)

            # 更新订阅列表（只在需要时）
            if hasattr(self, 'subscribed_symbols'):
                metrics.data.subscribed_symbols = list(self.subscribed_symbols)
            
            # 如果有延迟数据，更新统计
            if latency_ms is not None:
                timestamp = datetime.now(timezone.utc)
                metrics.data.add_latency(message_type, latency_ms, timestamp)
            else:
                # 只更新计数
                metrics.data.messages_received += 1
                metrics.data.messages_processed += 1
                      
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