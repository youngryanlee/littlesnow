# src/market/monitor/metrics.py
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Deque
from datetime import datetime
import statistics
from collections import defaultdict, deque
import math

from ..core.data_models import ExchangeType

class MessageStat:
    """消息统计数据结构"""
    count: int = 0
    last_time: Optional[int] = None
    latency_ewma: float = 0.0
    latency_p50: float = 0.0
    latency_p95: float = 0.0
    latency_p99: float = 0.0
    latency_min: float = float('inf')
    latency_max: float = 0.0
    throughput_1s: float = 0.0
    throughput_1m: float = 0.0
    last_update: Optional[int] = None  # 存储时间戳（毫秒）
    errors: int = 0
    
    def __post_init__(self):
        if self.latency_min == float('inf'):
            self.latency_min = 0.0
    
    def update(self, latency_ms: float, timestamp: datetime):
        """更新统计"""
        self.count += 1
        # 存储时间戳（毫秒）
        timestamp_ms = int(timestamp.timestamp() * 1000)
        self.last_time = timestamp_ms
        self.last_update = timestamp_ms  # 用于吞吐量计算
        
        # EWMA 更新
        alpha = 0.1
        self.latency_ewma = (
            alpha * latency_ms + (1 - alpha) * self.latency_ewma
        ) if self.latency_ewma > 0 else latency_ms
        
        # 更新极值
        self.latency_min = min(self.latency_min, latency_ms)
        self.latency_max = max(self.latency_max, latency_ms)
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "count": self.count,
            "last_time": self.last_time,
            "latency_ewma": self.latency_ewma,
            "latency_p50": self.latency_p50,
            "latency_p95": self.latency_p95,
            "latency_p99": self.latency_p99,
            "latency_min": self.latency_min,
            "latency_max": self.latency_max,
            "throughput_1s": self.throughput_1s,
            "throughput_1m": self.throughput_1m,
            "last_update": self.last_update,
            "errors": self.errors
        }        


@dataclass
class BaseMetrics:
    """监控指标基类 - 所有适配器共享的核心指标"""
    
    adapter_name: str
    exchange_type: str
    
    # === 连接状态 ===
    is_connected: bool = False
    connection_errors: int = 0
    last_heartbeat: Optional[datetime] = None
    subscribed_symbols: List[str] = field(default_factory=list)
    
    # === 延迟指标（核心）===
    latency_ms: List[float] = field(default_factory=list)  # 网络延迟
    processing_ms: List[float] = field(default_factory=list)  # 处理延迟
    
    # === 性能指标 ===
    messages_received: int = 0
    messages_processed: int = 0
    errors: int = 0
    
    def __post_init__(self):
        # 确保列表初始化
        if not isinstance(self.latency_ms, list):
            self.latency_ms = []
        if not isinstance(self.processing_ms, list):
            self.processing_ms = []
        if not isinstance(self.subscribed_symbols, list):
            self.subscribed_symbols = []
    
    @property
    def avg_latency(self) -> float:
        """平均延迟"""
        return statistics.mean(self.latency_ms) if self.latency_ms else 0.0
    
    @property
    def max_latency(self) -> float:
        """最大延迟"""
        return max(self.latency_ms) if self.latency_ms else 0.0
    
    @property
    def p50_latency(self) -> float:
        """P50延迟"""
        if not self.latency_ms:
            return 0.0
        return statistics.quantiles(self.latency_ms, n=100)[49] if len(self.latency_ms) >= 2 else self.avg_latency
    
    @property
    def p95_latency(self) -> float:
        """P95延迟"""
        if not self.latency_ms:
            return 0.0
        return statistics.quantiles(self.latency_ms, n=100)[94] if len(self.latency_ms) >= 2 else self.max_latency
    
    @property
    def p99_latency(self) -> float:
        """P99延迟"""
        if not self.latency_ms:
            return 0.0
        return statistics.quantiles(self.latency_ms, n=100)[98] if len(self.latency_ms) >= 2 else self.max_latency
    
    @property
    def throughput_1s(self) -> float:
        """每秒吞吐量（最后1秒）"""
        if len(self.latency_ms) < 2:
            return 0.0
        return len(self.latency_ms) / (self.latency_ms[-1] - self.latency_ms[0]) * 1000 if self.latency_ms[-1] > self.latency_ms[0] else 0.0
    
    @property
    def error_rate(self) -> float:
        """错误率"""
        total = self.messages_received + self.errors
        return self.errors / total if total > 0 else 0.0


@dataclass
class BinanceMetrics(BaseMetrics):
    """Binance特有的监控指标"""
    
    # === Binance特有指标 ===
    pending_buffer_sizes: List[int] = field(default_factory=list)
    update_gaps: List[int] = field(default_factory=list)
    snapshot_initialization_time: List[float] = field(default_factory=list)
    validation_ms: List[float] = field(default_factory=list)
    
    # === 订单簿验证指标 ===
    validations_total: int = 0
    validations_success: int = 0
    validations_failed: int = 0
    
    @property
    def validation_success_rate(self) -> float:
        """验证成功率"""
        total = self.validations_success + self.validations_failed
        return self.validations_success / total if total > 0 else 0.0
    
    @property
    def avg_validation_time(self) -> float:
        """平均验证时间"""
        return statistics.mean(self.validation_ms) if self.validation_ms else 0.0
    
    @property
    def avg_pending_buffer(self) -> float:
        """平均pending buffer大小"""
        return statistics.mean(self.pending_buffer_sizes) if self.pending_buffer_sizes else 0.0


@dataclass
class PolymarketMetrics(BaseMetrics):
    """Polymarket特有的监控指标"""
    
    # 使用 field 定义额外字段
    window_size: int = field(default=1000, init=False)
    latency_history: Dict[str, Deque[float]] = field(default_factory=dict, init=False)
    realtime_stats: Dict[str, MessageStat] = field(default_factory=dict, init=False)
    
    def __post_init__(self):
        super().__post_init__()
        
        # 延迟历史窗口
        self.window_size = 1000
        self.latency_history = defaultdict(lambda: deque(maxlen=self.window_size))
        
        # 实时统计
        self.realtime_stats = {
            "book": MessageStat(),
            "last_trade_price": MessageStat(),
            "price_change": MessageStat(),
            "all": MessageStat()
        }


class AdapterMetrics:
    """适配器监控指标容器 - 统一入口"""

    def __init__(self, adapter_name: str, exchange_type: str):
        """初始化适配器指标
        
        Args:
            adapter_name: 适配器名称
            exchange_type: 交易所类型
        """
        
        if exchange_type == ExchangeType.BINANCE:
            self.data = BinanceMetrics(adapter_name, exchange_type)
        elif exchange_type == ExchangeType.POLYMARKET:
            self.data = PolymarketMetrics(adapter_name, exchange_type)
        else:
            self.data = BaseMetrics(adapter_name, exchange_type)

    def __getattr__(self, name):
        """代理所有未定义的属性到 data 对象"""
        # 避免递归
        if name == 'data':
            raise AttributeError(f"'{self.__class__.__name__}' object has no attribute '{name}'")
        
        if hasattr(self.data, name):
            return getattr(self.data, name)
        else:
            raise AttributeError(f"'{self.__class__.__name__}' object has no attribute '{name}'")        
        
    def __setattr__(self, name, value):
        """代理属性设置到 data 对象"""
        # 处理特殊的属性（data 和以 _ 开头的属性）
        if name == 'data' or name.startswith('_'):
            object.__setattr__(self, name, value)
            return
        
        # 如果 data 有该属性，设置到 data
        if hasattr(self.data, name):
            setattr(self.data, name, value)
        else:
            # 否则设置到 AdapterMetrics 实例
            object.__setattr__(self, name, value)    
    
    @property
    def adapter_name(self) -> str:
        return self.data.adapter_name
    
    @property
    def exchange_type(self) -> str:
        return self.data.exchange_type
    
    def is_binance(self) -> bool:
        """是否是Binance适配器"""
        return isinstance(self.data, BinanceMetrics)
    
    def is_polymarket(self) -> bool:
        """是否是Polymarket适配器"""
        return isinstance(self.data, PolymarketMetrics)