# src/market/utils/time_sync.py

import statistics
import numpy as np
from typing import List, Deque, Optional
from collections import deque
import logging

logger = logging.getLogger(__name__)

class TimeSyncManager:
    """时间同步管理器，处理服务器和本地时间差"""
    
    def __init__(self, adapter_name: str, window_size: int = 100):
        self.adapter_name = adapter_name
        self.window_size = window_size
        
        # 滑动窗口存储offset样本
        self.offset_window: Deque[int] = deque(maxlen=window_size)
        
        # 当前估计的offset
        self.estimated_offset_ms: Optional[int] = None
        
        # EWMA参数
        self.alpha = 0.1  # 较小的alpha使估计更稳定
        self.ewma_offset = None
        
        # 校准状态
        self.is_calibrated = False
        self.min_samples_for_calibration = 10
        
    def update_offset(self, server_timestamp_ms: int, received_timestamp_ms: int) -> int:
        """
        更新时间偏移估计，返回校正后的延迟
        
        步骤：
        1. 计算当前offset: received - server
        2. 加入滑动窗口
        3. 使用稳健统计量估计offset
        4. 使用估计的offset校正延迟
        """
        
        # 1. 计算当前offset
        current_offset = received_timestamp_ms - server_timestamp_ms
        
        # 2. 加入滑动窗口
        self.offset_window.append(current_offset)
        
        # 3. 使用稳健统计量估计offset
        self._estimate_offset()
        
        # 4. 校正延迟
        if self.estimated_offset_ms is not None:
            # 校正后的延迟 = 测量延迟 - 估计的offset
            # 延迟 = (接收时间 - 服务器时间) - 估计offset
            corrected_latency = current_offset - self.estimated_offset_ms
            
            # 确保延迟非负（网络延迟不能为负）
            corrected_latency = max(corrected_latency, 0)
            
            # 记录调试信息
            if len(self.offset_window) % 20 == 0:  # 每20个样本记录一次
                logger.debug(
                    f"[{self.adapter_name}] Offset估计: "
                    f"当前={current_offset}ms, "
                    f"估计={self.estimated_offset_ms}ms, "
                    f"校正延迟={corrected_latency}ms, "
                    f"窗口大小={len(self.offset_window)}"
                )
            
            return corrected_latency
        else:
            # 还没有足够的样本进行估计，使用原始延迟（确保非负）
            return max(current_offset, 0)
    
    def _estimate_offset(self):
        """使用稳健统计量估计offset"""
        
        if len(self.offset_window) < self.min_samples_for_calibration:
            return
        
        # 方法1: 使用中位数（抗异常值能力强）
        median_offset = int(statistics.median(self.offset_window))
        
        # 方法2: 使用EWMA（指数加权移动平均）
        if self.ewma_offset is None:
            self.ewma_offset = median_offset
        else:
            # EWMA: new_estimate = alpha * current + (1-alpha) * previous
            self.ewma_offset = self.alpha * median_offset + (1 - self.alpha) * self.ewma_offset
        
        # 使用EWMA作为最终估计（更平滑）
        self.estimated_offset_ms = int(self.ewma_offset)
        
        # 标记为已校准
        if not self.is_calibrated and len(self.offset_window) >= self.min_samples_for_calibration:
            self.is_calibrated = True
            logger.info(
                f"[{self.adapter_name}] 时间偏移已校准: {self.estimated_offset_ms}ms "
                f"(窗口大小={len(self.offset_window)})"
            )
    
    def adjust_server_timestamp(self, server_timestamp_ms: int) -> int:
        """调整服务器时间戳，使其与本地时间对齐"""
        if self.estimated_offset_ms is not None:
            # 服务器时间 + offset = 本地时间
            return server_timestamp_ms + self.estimated_offset_ms
        return server_timestamp_ms
    
    def get_stats(self) -> dict:
        """获取时间同步统计"""
        if len(self.offset_window) == 0:
            return {}
        
        return {
            'estimated_offset_ms': self.estimated_offset_ms,
            'window_size': len(self.offset_window),
            'min_offset': min(self.offset_window) if self.offset_window else 0,
            'max_offset': max(self.offset_window) if self.offset_window else 0,
            'is_calibrated': self.is_calibrated,
            'ewma_offset': self.ewma_offset
        }
    
    def reset(self):
        """重置时间同步"""
        self.offset_window.clear()
        self.estimated_offset_ms = None
        self.ewma_offset = None
        self.is_calibrated = False
        logger.debug(f"[{self.adapter_name}] 时间同步已重置")