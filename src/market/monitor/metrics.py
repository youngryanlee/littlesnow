# src/market/monitor/metrics.py
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Deque
from datetime import datetime
import time
from decimal import Decimal
import statistics
from collections import defaultdict, deque

from ..core.data_models import ExchangeType
from .direction_detector_monitor import DirectionDetectorMonitor

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
    
    # === 性能指标 ===
    messages_received: int = 0
    messages_processed: int = 0
    errors: int = 0

    # === 延迟指标（核心）===
    window_size: int = field(default=1000, init=False)
    latency_history: Dict[str, Deque[float]] = field(default_factory=dict, init=False)
    message_stats: Dict[str, MessageStat] = field(default_factory=dict, init=False)  

    def __post_init__(self):
        # 确保列表初始化
        if not isinstance(self.subscribed_symbols, list):
            self.subscribed_symbols = []

        # 初始化统一统计结构
        self.window_size = 1000
        self.latency_history = defaultdict(lambda: deque(maxlen=self.window_size))
        
        # 初始化message_stats，确保有"all"
        self.message_stats = {
            "all": MessageStat()
        }    
    
    def add_latency(self, message_type: str, latency_ms: float, timestamp: datetime):
        """添加延迟样本 - 统一接口"""
        # 更新基础计数
        self.messages_received += 1
        self.messages_processed += 1  # 假设处理成功

        # 确保有"all"统计
        if "all" not in self.message_stats:
            self.message_stats["all"] = MessageStat()
            self.latency_history["all"] = deque(maxlen=self.window_size)
        
        # 更新统计
        if message_type not in self.message_stats:
            # 自动创建新的消息类型统计
            self.message_stats[message_type] = MessageStat()
            self.latency_history[message_type] = deque(maxlen=self.window_size)
        
        stats = self.message_stats[message_type]
        all_stats = self.message_stats["all"]
        
        # 更新统计
        stats.update(latency_ms, timestamp)
        all_stats.update(latency_ms, timestamp)
        
        # 添加到历史
        self.latency_history[message_type].append(latency_ms)
        self.latency_history["all"].append(latency_ms)
        
        # 定期计算百分位（每10条消息）
        if stats.count % 10 == 0 or stats.count == 10:
            self._update_percentiles(message_type)
        
        if all_stats.count % 10 == 0 or all_stats.count == 10:
            self._update_percentiles("all")
    
    def _update_percentiles(self, message_type: str):
        """更新百分位统计"""
        try:
            history = self.latency_history[message_type]
            if len(history) < 10:
                return
                
            latencies = list(history)
            sorted_latencies = sorted(latencies)
            n = len(sorted_latencies)
            
            stats = self.message_stats[message_type]
            
            # 计算百分位
            stats.latency_p50 = sorted_latencies[n // 2]
            idx_95 = min(int(n * 0.95), n - 1)
            stats.latency_p95 = sorted_latencies[idx_95]
            idx_99 = min(int(n * 0.99), n - 1)
            stats.latency_p99 = sorted_latencies[idx_99]
                
        except Exception:
            pass  # 忽略计算错误
        
    def _get_percentile(self, percentile: int) -> float:
        """获取百分位 - 实时计算"""
        history = self.latency_history.get("all")
        if not history or len(history) < 5:
            return 0.0
            
        latencies = list(history)
        if len(latencies) < 5:
            return 0.0
            
        sorted_latencies = sorted(latencies)
        n = len(sorted_latencies)
        
        # 计算百分位索引
        idx = min(int(n * percentile / 100), n - 1)
        result = sorted_latencies[idx]
        
        # 同时更新MessageStat中的值，避免下次再计算
        stats = self.message_stats.get("all")
        if stats:
            if percentile == 50:
                stats.latency_p50 = result
            elif percentile == 95:
                stats.latency_p95 = result
            elif percentile == 99:
                stats.latency_p99 = result
        
        return result    
    
    @property
    def error_rate(self) -> float:
        """错误率"""
        if self.messages_received == 0:
            return 0.0
        return self.errors / self.messages_received
    
    @property
    def avg_latency(self) -> float:
        """平均延迟 - 从all统计获取"""
        stats = self.message_stats.get("all")
        return stats.latency_ewma if stats else 0.0
    
    @property
    def max_latency(self) -> float:
        """最大延迟"""
        stats = self.message_stats.get("all")
        return stats.latency_max if stats else 0.0
    
    # 修改获取属性，实时计算
    @property
    def p50_latency(self) -> float:
        """P50延迟"""
        return self._get_percentile(50)
    
    @property
    def p95_latency(self) -> float:
        """P95延迟"""
        return self._get_percentile(95)
    
    @property
    def p99_latency(self) -> float:
        """P99延迟"""
        return self._get_percentile(99)
    
    @property
    def throughput_1s(self) -> float:
        """每秒吞吐量（最后1秒）"""
        if len(self.latency_ms) < 2:
            return 0.0
        return len(self.latency_ms) / (self.latency_ms[-1] - self.latency_ms[0]) * 1000 if self.latency_ms[-1] > self.latency_ms[0] else 0.0


@dataclass
class BinanceMetrics(BaseMetrics):
    """Binance特有的监控指标"""
    
    # === Binance特有指标 ===
    pending_buffer_sizes: List[int] = field(default_factory=list)
    validation_time: List[float] = field(default_factory=list)
    
    # === 订单簿验证指标 ===
    validations_total: int = 0
    validations_success: int = 0
    validations_failed: int = 0
    validations_warnings: int = 0

    # === T0 Signal指标 ===
    t0_monitor: DirectionDetectorMonitor = DirectionDetectorMonitor()


    def __post_init__(self):
        super().__post_init__()
        # Binance特有的消息类型
        self.message_stats.update({
            "depthUpdate": MessageStat(),  # 深度更新
            "trade": MessageStat(),  # 交易
            "all": MessageStat(),
        })
    
    @property
    def validation_success_rate(self) -> float:
        """验证成功率"""
        return self.validations_success / self.validations_total if self.validations_total > 0 else 0.0
    
    @property
    def avg_pending_buffer(self) -> float:
        """平均pending buffer大小"""
        return statistics.mean(self.pending_buffer_sizes) if self.pending_buffer_sizes else 0.0
    
    @property
    def t0_rate(self) -> float:
        """t0信号率"""
        return self.t0_monitor.total_signals / self.message_stats['trade'].count if self.message_stats['trade'].count > 0 else 0.0


@dataclass
class PolymarketMetrics(BaseMetrics):
    """Polymarket特有的监控指标"""
    
    def __post_init__(self):
        super().__post_init__()
        
        # 实时统计
        self.message_stats = {
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