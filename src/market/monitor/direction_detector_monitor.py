# src/market/monitor/direction_detector_monitor.py
import time
from dataclasses import dataclass, field
from typing import Dict, List, Deque, Optional, Tuple
from collections import deque
from decimal import Decimal
import statistics
import numpy as np

@dataclass
class SignalRecord:
    """信号记录"""
    timestamp: int  # 毫秒时间戳
    direction: str
    mid_price: Decimal
    trade_id: str
    success: Optional[bool] = None  # 是否成功，后续评估
    actual_duration_ms: Optional[int] = None  # 实际持续时间
    profit_pct: Optional[Decimal] = None  # 盈利百分比

@dataclass
class StateTransitionRecord:
    """状态转换记录"""
    timestamp: int  # 毫秒时间戳
    from_state: Optional[str]
    to_state: Optional[str]
    reason: str

class DirectionDetectorMonitor:
    """T0信号检测器的监控系统"""
    
    def __init__(self, window_minutes: int = 5):
        # 数据存储
        self.total_signals: int = 0
        self.signals: Deque[SignalRecord] = deque(maxlen=10000)  # 最近10000个信号
        self.state_transitions: Deque[StateTransitionRecord] = deque(maxlen=10000)
        
        # 监控开始时间（用于计算平均速率）
        self.start_time_ms: int = int(time.time() * 1000)
        
        # 冷却时间记录
        self.total_cooldown: int = 0
        self.cooldown_intervals: List[int] = []  # 实际冷却间隔(ms)
        
        # 误判记录
        self.false_signals: List[SignalRecord] = []  # 被判定为错误的信号

        # 添加调试计数器
        self.debug_counts = {
            'total_trades_processed': 0,
            'cooling_triggers': 0,
            'direction_detection_calls': 0,
            'up_signals': 0,
            'down_signals': 0,
            'no_direction': 0
        }
        
    def record_signal(self, signal: SignalRecord):
        """记录一个新的信号"""
        self.total_signals += 1
        self.signals.append(signal)

        # 调试计数
        if signal.direction == "UP":
            self.debug_counts['up_signals'] += 1
        elif signal.direction == "DOWN":
            self.debug_counts['down_signals'] += 1
        else:
            self.debug_counts['no_direction'] += 1
        print(f"DEBUG: 记录信号 #{self.total_signals}: direction={signal.direction}, "
              f"time={signal.timestamp}, up_count={self.debug_counts['up_signals']}, "
              f"down_count={self.debug_counts['down_signals']}")

    
    def record_state_transition(self, transition: StateTransitionRecord):
        """记录状态转换"""
        self.state_transitions.append(transition)
    
    def record_cooldown_interval(self, interval_ms: int):
        """记录实际冷却间隔"""
        self.total_cooldown += 1
        self.cooldown_intervals.append(interval_ms)
        # 只保留最近1000个记录
        if len(self.cooldown_intervals) > 1000:
            self.cooldown_intervals.pop(0)
    
    def mark_signal_result(self, signal: SignalRecord, success: bool, 
                          actual_duration_ms: Optional[int] = None,
                          profit_pct: Optional[Decimal] = None):
        """标记信号的结果（成功/失败）"""
        # 找到对应的信号并更新
        for s in self.signals:
            if s.trade_id == signal.trade_id:
                s.success = success
                s.actual_duration_ms = actual_duration_ms
                s.profit_pct = profit_pct
                
                if not success:
                    self.false_signals.append(s)
                break
    
    def calculate_metrics(self) -> Dict:
        """计算所有监控指标"""
        current_time_ms = int(time.time() * 1000)
        monitoring_duration_minutes = (current_time_ms - self.start_time_ms) / (1000 * 60)
        
        # 1. 最近1分钟信号数
        recent_signals_per_minute = self._calculate_recent_signals_per_minute(current_time_ms)
        
        # 2. 平均每分钟信号数（从监控开始）
        avg_signals_per_minute = self._calculate_avg_signals_per_minute(monitoring_duration_minutes)
        
        # 3. 最近1分钟状态转换数
        recent_transitions_per_minute = self._calculate_recent_transitions_per_minute(current_time_ms)
        
        # 4. 误报率
        false_positive_rate = self._calculate_false_positive_rate()
        
        # 5. 其他指标
        additional_metrics = self._calculate_additional_metrics(current_time_ms, monitoring_duration_minutes)
        
        # 组合所有指标
        metrics = {
            'total_signals': self.total_signals,
            'recent_signals_per_minute': recent_signals_per_minute,  # 最近1分钟
            'avg_signals_per_minute': avg_signals_per_minute,        # 平均
            'recent_transitions_per_minute': recent_transitions_per_minute,
            'false_positive_rate': false_positive_rate,
            'monitoring_duration_minutes': monitoring_duration_minutes,
            'timestamp': current_time_ms / 1000,  # 转换为秒
            **additional_metrics
        }
        
        return metrics
    
    def _calculate_recent_signals_per_minute(self, current_time_ms: int) -> float:
        """计算最近1分钟的信号数"""
        one_minute_ago = current_time_ms - (60 * 1000)  # 1分钟前的毫秒时间
        
        # 统计最近1分钟内的信号数量
        recent_signals = sum(1 for s in self.signals if s.timestamp >= one_minute_ago)
        
        # 直接返回信号数量（因为时间窗口固定为1分钟）
        return float(recent_signals)
    
    def _calculate_avg_signals_per_minute(self, monitoring_duration_minutes: float) -> float:
        """计算平均每分钟信号数"""
        if monitoring_duration_minutes <= 0:
            return 0.0
        
        return float(self.total_signals) / monitoring_duration_minutes
    
    def _calculate_recent_transitions_per_minute(self, current_time_ms: int) -> float:
        """计算最近1分钟的状态转换数"""
        one_minute_ago = current_time_ms - (60 * 1000)
        
        # 统计最近1分钟内的状态转换
        recent_transitions = sum(1 for t in self.state_transitions if t.timestamp >= one_minute_ago)
        
        return float(recent_transitions)
    
    def _calculate_false_positive_rate(self) -> float:
        """计算误报率"""
        evaluated_signals = [s for s in self.signals if s.success is not None]
        
        if not evaluated_signals:
            return 0.0
        
        false_count = sum(1 for s in evaluated_signals if s.success is False)
        
        return false_count / len(evaluated_signals)
    
    def _calculate_additional_metrics(self, current_time_ms: int, 
                                    monitoring_duration_minutes: float) -> Dict:
        """计算多时间窗口的重要指标"""
        metrics = {}
        
        # 定义多个时间窗口
        time_windows = {
            'recent_1min': 60 * 1000,      # 最近1分钟
            'recent_5min': 5 * 60 * 1000,  # 最近5分钟
            'recent_15min': 15 * 60 * 1000, # 最近15分钟
            'all_time': None               # 全局
        }
        
        # 1. 多时间窗口的方向分布
        metrics['direction_distribution'] = {}
        for window_name, window_ms in time_windows.items():
            if window_name == 'all_time':
                signals = list(self.signals)  # 所有信号
            else:
                cutoff_time = current_time_ms - window_ms
                signals = [s for s in self.signals if s.timestamp >= cutoff_time]
            
            if signals:
                directions = [s.direction for s in signals]
                up_count = sum(1 for d in directions if d == "UP")
                down_count = len(directions) - up_count
                
                metrics['direction_distribution'][window_name] = {
                    'up_percentage': up_count / len(directions) if directions else 0.0,
                    'down_percentage': down_count / len(directions) if directions else 0.0,
                    'up_count': up_count,
                    'down_count': down_count,
                    'total_signals': len(signals),
                    'signals_per_minute': len(signals) / (window_ms / (1000 * 60)) if window_ms else 0.0
                }
            else:
                metrics['direction_distribution'][window_name] = {
                    'up_percentage': 0.0,
                    'down_percentage': 0.0,
                    'up_count': 0,
                    'down_count': 0,
                    'total_signals': 0,
                    'signals_per_minute': 0.0
                }
        
        # 2. 多时间窗口的信号间隔（只在有足够信号时计算）
        metrics['signal_intervals'] = {}
        for window_name, window_ms in time_windows.items():
            if window_name == 'all_time':
                window_signals = list(self.signals)
            else:
                cutoff_time = current_time_ms - window_ms
                window_signals = [s for s in self.signals if s.timestamp >= cutoff_time]
            
            window_signals_sorted = sorted(window_signals, key=lambda x: x.timestamp)
            
            if len(window_signals_sorted) >= 2:
                intervals = []
                for i in range(1, len(window_signals_sorted)):
                    interval = window_signals_sorted[i].timestamp - window_signals_sorted[i-1].timestamp
                    intervals.append(interval)
                
                if intervals:
                    metrics['signal_intervals'][window_name] = {
                        'avg_interval_ms': statistics.mean(intervals),
                        'min_interval_ms': min(intervals),
                        'max_interval_ms': max(intervals),
                        'median_interval_ms': statistics.median(intervals),
                        'interval_count': len(intervals),
                        'signals_per_minute': len(window_signals) / (window_ms / (1000 * 60)) if window_ms else 0.0
                    }
                else:
                    metrics['signal_intervals'][window_name] = {
                        'avg_interval_ms': 0.0,
                        'min_interval_ms': 0.0,
                        'max_interval_ms': 0.0,
                        'median_interval_ms': 0.0,
                        'interval_count': 0,
                        'signals_per_minute': 0.0
                    }
            else:
                metrics['signal_intervals'][window_name] = {
                    'avg_interval_ms': 0.0,
                    'min_interval_ms': 0.0,
                    'max_interval_ms': 0.0,
                    'median_interval_ms': 0.0,
                    'interval_count': 0,
                    'signals_per_minute': 0.0
                }
        
        # 3. 性能统计（按时间分组）
        metrics['performance'] = self._calculate_performance_metrics(current_time_ms)
        
        # 4. 趋势指标（新增）
        metrics['trend_indicators'] = self._calculate_trend_indicators(current_time_ms)
        
        # 5. 冷却统计（如果有数据）
        metrics['cooldown_stats'] = self.get_cooldown_statistics()
        
        # 6. 警报标志（新增）
        metrics['alert_flags'] = self._calculate_alert_flags(current_time_ms)
        
        # 7. 总体统计
        metrics['overall_stats'] = {
            'total_signals': self.total_signals,
            'monitoring_duration_minutes': monitoring_duration_minutes,
            'signals_per_hour': (self.total_signals / monitoring_duration_minutes * 60) 
                                if monitoring_duration_minutes > 0 else 0.0,
            'uptime_minutes': monitoring_duration_minutes,
            'data_points': len(self.signals),
            'cooldown_data_points': len(self.cooldown_intervals) if hasattr(self, 'cooldown_intervals') else 0
        }
        
        return metrics

    def _calculate_performance_metrics(self, current_time_ms: int) -> Dict:
        """计算多时间窗口的性能统计"""
        performance_metrics = {}
        
        # 定义多个时间窗口
        time_windows = {
            'recent_1min': 60 * 1000,      # 最近1分钟
            'recent_5min': 5 * 60 * 1000,  # 最近5分钟
            'recent_15min': 15 * 60 * 1000, # 最近15分钟
            'all_time': None               # 全局
        }
        
        for window_name, window_ms in time_windows.items():
            if window_name == 'all_time':
                # 所有已评估信号
                evaluated_signals = [s for s in self.signals if s.success is not None]
            else:
                # 指定时间窗口内的已评估信号
                cutoff_time = current_time_ms - window_ms
                evaluated_signals = [
                    s for s in self.signals 
                    if s.success is not None and s.timestamp >= cutoff_time
                ]
            
            if not evaluated_signals:
                performance_metrics[window_name] = {
                    'success_rate': 0.0,
                    'total_evaluated': 0,
                    'profitable_count': 0,
                    'avg_profit_pct': 0.0,
                    'max_profit_pct': 0.0,
                    'min_profit_pct': 0.0,
                    'win_rate': 0.0,
                    'avg_win_pct': 0.0,
                    'avg_loss_pct': 0.0,
                    'profit_factor': 0.0
                }
                continue
            
            # 统计成功率和盈利
            success_count = sum(1 for s in evaluated_signals if s.success)
            success_rate = success_count / len(evaluated_signals)
            
            profitable_signals = [s for s in evaluated_signals 
                                if s.profit_pct is not None and s.profit_pct > 0]
            loss_signals = [s for s in evaluated_signals 
                        if s.profit_pct is not None and s.profit_pct < 0]
            
            # 基础统计
            avg_profit = 0.0
            max_profit = 0.0
            min_profit = 0.0
            avg_win = 0.0
            avg_loss = 0.0
            profit_factor = 0.0
            
            if profitable_signals:
                profits = [float(s.profit_pct) for s in profitable_signals]
                avg_profit = statistics.mean(profits)
                max_profit = max(profits)
                min_profit = min(profits)
                avg_win = avg_profit
            
            if loss_signals:
                losses = [float(s.profit_pct) for s in loss_signals]
                avg_loss = statistics.mean(losses)
                min_profit = min(losses) if not profitable_signals else min_profit
            
            # 盈利因子（总盈利/总亏损的绝对值）
            if loss_signals:
                total_profit = sum(max(float(s.profit_pct), 0) for s in evaluated_signals 
                                if s.profit_pct is not None)
                total_loss = abs(sum(min(float(s.profit_pct), 0) for s in evaluated_signals 
                                if s.profit_pct is not None))
                profit_factor = total_profit / total_loss if total_loss > 0 else float('inf')
            
            # 胜率（盈利信号比例）
            win_rate = len(profitable_signals) / len(evaluated_signals)
            
            performance_metrics[window_name] = {
                'success_rate': success_rate,
                'total_evaluated': len(evaluated_signals),
                'profitable_count': len(profitable_signals),
                'loss_count': len(loss_signals),
                'avg_profit_pct': avg_profit,
                'max_profit_pct': max_profit,
                'min_profit_pct': min_profit,
                'win_rate': win_rate,
                'avg_win_pct': avg_win,
                'avg_loss_pct': avg_loss,
                'profit_factor': profit_factor
            }
        
        return performance_metrics

    def _calculate_trend_indicators(self, current_time_ms: int) -> Dict:
        """计算趋势指标，反映策略表现的变化"""
        indicators = {}
        
        # 1. 信号频率趋势（最近5分钟 vs 前5分钟）
        five_min_ago = current_time_ms - (5 * 60 * 1000)
        ten_min_ago = current_time_ms - (10 * 60 * 1000)
        
        recent_signals = [s for s in self.signals if s.timestamp >= five_min_ago]
        previous_signals = [s for s in self.signals if ten_min_ago <= s.timestamp < five_min_ago]
        
        recent_count = len(recent_signals)
        previous_count = len(previous_signals)
        
        if previous_count > 0:
            frequency_change = (recent_count - previous_count) / previous_count
        else:
            frequency_change = 0.0
        
        indicators['frequency_trend'] = {
            'recent_5min': recent_count,
            'previous_5min': previous_count,
            'frequency_change_pct': frequency_change * 100,
            'trend': 'increasing' if frequency_change > 0.1 else 'decreasing' if frequency_change < -0.1 else 'stable',
            'significance': 'significant' if abs(frequency_change) > 0.3 else 'moderate' if abs(frequency_change) > 0.1 else 'minor'
        }
        
        # 2. 方向趋势（最近信号的方向变化）
        if len(recent_signals) >= 3:
            # 检查最近3个信号的方向一致性
            last_3_signals = recent_signals[-3:] if len(recent_signals) >= 3 else recent_signals
            last_3_directions = [s.direction for s in last_3_signals]
            
            if last_3_directions:
                same_direction_count = sum(1 for d in last_3_directions if d == last_3_directions[-1])
                consistency = same_direction_count / len(last_3_directions)
                
                indicators['direction_momentum'] = {
                    'last_3_directions': last_3_directions,
                    'consistency': consistency,
                    'current_bias': last_3_directions[-1],
                    'momentum': 'strong' if consistency >= 0.8 else 'moderate' if consistency >= 0.67 else 'weak'
                }
        
        # 3. 信号间隔趋势（是否在变快或变慢）
        if len(recent_signals) >= 4:
            sorted_signals = sorted(recent_signals, key=lambda x: x.timestamp)
            intervals = [sorted_signals[i].timestamp - sorted_signals[i-1].timestamp 
                        for i in range(1, len(sorted_signals))]
            
            if len(intervals) >= 3:
                # 计算间隔的变化率（滑动窗口）
                half = len(intervals) // 2
                first_half_avg = statistics.mean(intervals[:half]) if half > 0 else 0
                second_half_avg = statistics.mean(intervals[half:]) if len(intervals) - half > 0 else 0
                
                if first_half_avg > 0:
                    interval_change = (second_half_avg - first_half_avg) / first_half_avg
                else:
                    interval_change = 0.0
                
                trend_direction = 'slowing' if interval_change > 0.1 else 'accelerating' if interval_change < -0.1 else 'stable'
                
                indicators['interval_trend'] = {
                    'first_half_avg_ms': first_half_avg,
                    'second_half_avg_ms': second_half_avg,
                    'interval_change_pct': interval_change * 100,
                    'trend': trend_direction,
                    'significance': 'significant' if abs(interval_change) > 0.3 else 'moderate' if abs(interval_change) > 0.1 else 'minor'
                }
        
        # 4. 性能趋势（如果有足够评估数据）
        evaluated_signals = [s for s in self.signals if s.success is not None]
        
        if len(evaluated_signals) >= 10:
            # 按时间分成两半，比较成功率变化
            sorted_evaluated = sorted(evaluated_signals, key=lambda x: x.timestamp)
            half = len(sorted_evaluated) // 2
            
            first_half = sorted_evaluated[:half]
            second_half = sorted_evaluated[half:]
            
            first_success_rate = sum(1 for s in first_half if s.success) / len(first_half) if first_half else 0
            second_success_rate = sum(1 for s in second_half if s.success) / len(second_half) if second_half else 0
            
            if first_success_rate > 0:
                success_change = (second_success_rate - first_success_rate) / first_success_rate
            else:
                success_change = 0.0
            
            indicators['performance_trend'] = {
                'first_half_success_rate': first_success_rate,
                'second_half_success_rate': second_success_rate,
                'success_change_pct': success_change * 100,
                'trend': 'improving' if success_change > 0.1 else 'declining' if success_change < -0.1 else 'stable',
                'significance': 'significant' if abs(success_change) > 0.3 else 'moderate' if abs(success_change) > 0.1 else 'minor'
            }
        
        # 5. 方向平衡趋势（UP/DOWN比例变化）
        if len(recent_signals) >= 10:
            # 最近10个信号的方向分布
            last_10_signals = recent_signals[-10:] if len(recent_signals) >= 10 else recent_signals
            up_count = sum(1 for s in last_10_signals if s.direction == "UP")
            down_count = len(last_10_signals) - up_count
            
            # 前10个信号的方向分布（如果可能）
            if len(previous_signals) >= 10:
                prev_10_signals = previous_signals[-10:]
                prev_up_count = sum(1 for s in prev_10_signals if s.direction == "UP")
                prev_down_count = len(prev_10_signals) - prev_up_count
                
                prev_up_ratio = prev_up_count / len(prev_10_signals) if prev_10_signals else 0.5
                current_up_ratio = up_count / len(last_10_signals) if last_10_signals else 0.5
                
                direction_change = current_up_ratio - prev_up_ratio
                
                indicators['direction_balance_trend'] = {
                    'prev_up_ratio': prev_up_ratio,
                    'current_up_ratio': current_up_ratio,
                    'direction_change': direction_change,
                    'trend': 'more_up' if direction_change > 0.2 else 'more_down' if direction_change < -0.2 else 'balanced',
                    'bias_shift': 'towards_up' if direction_change > 0 else 'towards_down' if direction_change < 0 else 'stable'
                }
        
        return indicators
    
    def get_cooldown_statistics(self) -> Dict:
        """获取冷却时间详细统计"""
        if not self.cooldown_intervals:
            return {}
        
        intervals = self.cooldown_intervals
        
        return {
            'mean': statistics.mean(intervals),
            'median': statistics.median(intervals),
            'std': statistics.stdev(intervals) if len(intervals) > 1 else 0.0,
            'min': min(intervals),
            'max': max(intervals),
            'percentile_25': np.percentile(intervals, 25) if intervals else 0.0,
            'percentile_75': np.percentile(intervals, 75) if intervals else 0.0,
            'count': self.total_cooldown
        }
    
    def _calculate_alert_flags(self, current_time_ms: int) -> Dict:
        """计算警报标志"""
        alerts = {
            'warnings': [],
            'errors': [],
            'info': []
        }
        
        # 1. 无信号警报
        one_min_ago = current_time_ms - (60 * 1000)
        recent_signals = [s for s in self.signals if s.timestamp >= one_min_ago]
        
        if len(recent_signals) == 0 and self.total_signals > 10 and (current_time_ms - self.start_time_ms) > 300000:
            # 运行超过5分钟后，最近1分钟没有信号
            alerts['warnings'].append({
                'code': 'NO_RECENT_SIGNALS',
                'message': '最近1分钟没有检测到信号',
                'severity': 'medium',
                'suggestion': '检查市场数据或调整检测参数'
            })
        
        # 2. 方向极端偏差警报
        if len(recent_signals) >= 5:
            up_count = sum(1 for s in recent_signals if s.direction == "UP")
            up_ratio = up_count / len(recent_signals)
            
            if up_ratio > 0.9:
                alerts['warnings'].append({
                    'code': 'EXTREME_UP_BIAS',
                    'message': f'极端UP偏向：最近{len(recent_signals)}个信号中{up_count}个是UP ({up_ratio:.0%})',
                    'severity': 'low',
                    'suggestion': '检查DOWN信号检测条件是否过严'
                })
            elif up_ratio < 0.1:
                alerts['warnings'].append({
                    'code': 'EXTREME_DOWN_BIAS',
                    'message': f'极端DOWN偏向：最近{len(recent_signals)}个信号中{len(recent_signals)-up_count}个是DOWN ({1-up_ratio:.0%})',
                    'severity': 'low',
                    'suggestion': '检查UP信号检测条件是否过严'
                })
        
        # 3. 信号频率异常警报
        if len(self.signals) >= 20:
            # 计算最近1分钟和平均频率的对比
            avg_signals_per_minute = self.total_signals / ((current_time_ms - self.start_time_ms) / (1000 * 60))
            
            if avg_signals_per_minute > 0:
                recent_rate = len(recent_signals)
                ratio = recent_rate / avg_signals_per_minute
                
                if ratio > 5:
                    alerts['errors'].append({
                        'code': 'FREQUENCY_SURGE',
                        'message': f'信号频率异常飙升：{recent_rate}/min (平均{avg_signals_per_minute:.1f}/min)',
                        'severity': 'high',
                        'suggestion': '可能市场异常波动，检查检测条件'
                    })
                elif ratio < 0.2 and recent_rate < 1:
                    alerts['warnings'].append({
                        'code': 'FREQUENCY_DROP',
                        'message': f'信号频率异常下降：{recent_rate}/min (平均{avg_signals_per_minute:.1f}/min)',
                        'severity': 'medium',
                        'suggestion': '市场可能过于平静，或检测条件过严'
                    })
        
        # 4. 信号间隔异常警报
        if len(recent_signals) >= 3:
            sorted_signals = sorted(recent_signals, key=lambda x: x.timestamp)
            intervals = [sorted_signals[i].timestamp - sorted_signals[i-1].timestamp 
                        for i in range(1, len(sorted_signals))]
            
            if intervals:
                avg_interval = statistics.mean(intervals)
                if avg_interval < 100:  # 小于100ms
                    alerts['errors'].append({
                        'code': 'INTERVAL_TOO_SHORT',
                        'message': f'信号间隔过短：平均{avg_interval:.1f}ms',
                        'severity': 'high',
                        'suggestion': '检查冷却机制是否失效'
                    })
        
        # 5. 冷却机制异常警报
        if hasattr(self, 'cooldown_intervals') and len(self.cooldown_intervals) > 10:
            avg_cooldown = statistics.mean(self.cooldown_intervals)
            
            if avg_cooldown < 10 and self.total_signals > 5:
                alerts['errors'].append({
                    'code': 'COOLDOWN_INEFFECTIVE',
                    'message': f'冷却机制可能失效：平均冷却间隔{avg_cooldown:.1f}ms',
                    'severity': 'high',
                    'suggestion': '检查冷却参数和逻辑'
                })
        
        # 如果没有警报，添加一个正常信息
        if not alerts['warnings'] and not alerts['errors']:
            alerts['info'].append({
                'code': 'SYSTEM_NORMAL',
                'message': '系统运行正常',
                'severity': 'low'
            })
        
        return alerts
    
    def reset_monitoring(self):
        """重置监控数据"""
        self.total_signals = 0
        self.signals.clear()
        self.state_transitions.clear()
        self.cooldown_intervals.clear()
        self.false_signals.clear()
        self.start_time_ms = int(time.time() * 1000)
    
    def generate_report(self) -> str:
        """生成监控报告"""
        metrics = self.calculate_metrics()
        
        report_lines = [
            "=== T0信号检测器监控报告 ===",
            f"报告时间: {time.strftime('%Y-%m-%d %H:%M:%S')}",
            f"监控时长: {metrics['monitoring_duration_minutes']:.1f} 分钟",
            "",
            "📊 核心指标:",
            f"  总信号数: {metrics['total_signals']}",
            f"  最近1分钟信号数: {metrics['recent_signals_per_minute']:.1f}",
            f"  平均每分钟信号数: {metrics['avg_signals_per_minute']:.2f}",
            f"  平均冷却时间: {metrics['avg_cooldown_used']:.1f} ms",
            f"  最近1分钟状态转换: {metrics['recent_transitions_per_minute']:.1f}",
            f"  误报率: {metrics['false_positive_rate']:.2%}",
        ]
        
        # 方向分布
        dist = metrics['direction_distribution']
        report_lines.extend([
            "",
            "📈 方向分布（最近1分钟）:",
            f"  UP信号: {dist['up_count']} ({dist['up_percentage']:.1%})",
            f"  DOWN信号: {dist['down_count']} ({dist['down_percentage']:.1%})",
            f"  总计: {dist['recent_total']}",
        ])
        
        # 信号间隔
        if 'signal_intervals' in metrics:
            intervals = metrics['signal_intervals']
            if intervals['interval_count'] > 0:
                report_lines.extend([
                    "",
                    "⏱️ 信号间隔统计（最近1分钟）:",
                    f"  平均间隔: {intervals['avg_interval_ms']:.1f} ms",
                    f"  最小间隔: {intervals['min_interval_ms']:.1f} ms",
                    f"  最大间隔: {intervals['max_interval_ms']:.1f} ms",
                    f"  中位数间隔: {intervals['median_interval_ms']:.1f} ms",
                    f"  间隔数量: {intervals['interval_count']}",
                ])
        
        # 性能指标
        if 'performance' in metrics:
            perf = metrics['performance']
            if perf['total_evaluated'] > 0:
                report_lines.extend([
                    "",
                    "🎯 性能指标:",
                    f"  成功率: {perf['success_rate']:.2%}",
                    f"  已评估信号: {perf['total_evaluated']}",
                    f"  盈利信号: {perf['profitable_count']}",
                ])
                if perf['profitable_count'] > 0:
                    report_lines.extend([
                        f"  平均盈利: {perf['avg_profit_pct']:.4f}%",
                        f"  最大盈利: {perf['max_profit_pct']:.4f}%",
                        f"  最小盈利: {perf['min_profit_pct']:.4f}%",
                    ])
        
        # 冷却时间统计
        if 'cooldown_stats' in metrics:
            stats = metrics['cooldown_stats']
            report_lines.extend([
                "",
                "🔄 冷却时间统计:",
                f"  平均: {stats['mean']:.1f} ms",
                f"  中位数: {stats['median']:.1f} ms",
                f"  标准差: {stats['std']:.1f} ms",
                f"  范围: {stats['min']:.1f} - {stats['max']:.1f} ms",
                f"  样本数: {stats['count']}",
            ])
        
        return "\n".join(report_lines)
    
    def generate_detailed_diagnostic(self) -> str:
        """生成详细的诊断报告"""
        metrics = self.calculate_metrics()
        
        report = [
            "=== T0信号检测器诊断报告 ===",
            f"报告时间: {time.strftime('%Y-%m-%d %H:%M:%S')}",
            "",
            "📊 数据统计:",
            f"  总运行时间: {metrics['monitoring_duration_minutes']:.2f} 分钟",
            f"  总信号数: {metrics['total_signals']}",
            f"  平均每分钟信号数: {metrics['avg_signals_per_minute']:.2f}",
            f"  最近1分钟信号数: {metrics['recent_signals_per_minute']:.1f}",
            "",
            "🔄 冷却机制分析:",
            f"  冷却触发次数: {metrics.get('cooling_count', 0)}",
            f"  平均冷却间隔: {metrics.get('avg_cooldown_used', 0):.1f} ms",
            f"  每分钟冷却次数: {metrics.get('cooling_rate_per_minute', 0):.2f}",
            f"  冷却成功率: {metrics.get('cooling_success_ratio', 0):.4f} (每个信号对应的冷却次数)",
        ]
        
        if metrics.get('cooling_count', 0) > 0:
            ratio = metrics['total_signals'] / metrics['cooling_count']
            report.append(f"  信号/冷却比例: {ratio:.4f} (约{1/ratio:.0f}次冷却产生1个信号)")
        
        report.extend([
            "",
            "📈 方向分布分析:",
            f"  UP信号: {metrics['direction_distribution']['up_count']} "
            f"({metrics['direction_distribution']['up_percentage']:.1%})",
            f"  DOWN信号: {metrics['direction_distribution']['down_count']} "
            f"({metrics['direction_distribution']['down_percentage']:.1%})",
            f"  最近总信号: {metrics['direction_distribution']['recent_total']}",
            f"  总信号: {metrics['total_signals']}",
        ])
        
        # 分析方向分布的问题
        total = metrics['total_signals']
        up = metrics['direction_distribution']['up_count']
        down = metrics['direction_distribution']['down_count']
        
        if total > 0 and (up + down) != total:
            other = total - (up + down)
            report.append(f"  ❗ 异常: 有{other}个信号方向既不是UP也不是DOWN")
        
        # 信号间隔分析
        if 'signal_intervals' in metrics:
            intervals = metrics['signal_intervals']
            if intervals.get('interval_count', 0) > 0:
                report.extend([
                    "",
                    "⏱️ 信号间隔统计:",
                    f"  平均间隔: {intervals['avg_interval_ms']:.1f} ms ({intervals['avg_interval_ms']/1000:.1f}秒)",
                    f"  最小间隔: {intervals['min_interval_ms']:.1f} ms",
                    f"  最大间隔: {intervals['max_interval_ms']:.1f} ms",
                    f"  间隔数量: {intervals['interval_count']}",
                ])
                
                # 计算理论信号频率
                if intervals['avg_interval_ms'] > 0:
                    theoretical_per_minute = 60000 / intervals['avg_interval_ms']
                    report.append(f"  理论每分钟信号数: {theoretical_per_minute:.2f}")
        
        # 调试信息
        if hasattr(self, 'debug_counts'):
            report.extend([
                "",
                "🐛 调试计数:",
                f"  总交易处理次数: {self.debug_counts.get('total_trades_processed', 0)}",
                f"  冷却触发次数: {self.debug_counts.get('cooling_triggers', 0)}",
                f"  方向检测调用: {self.debug_counts.get('direction_detection_calls', 0)}",
                f"  UP信号: {self.debug_counts.get('up_signals', 0)}",
                f"  DOWN信号: {self.debug_counts.get('down_signals', 0)}",
                f"  无方向: {self.debug_counts.get('no_direction', 0)}",
            ])
        
        return "\n".join(report)