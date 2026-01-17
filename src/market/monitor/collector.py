# src/market/monitor/collector.py
import time
from typing import Dict, List, Optional, Any
from datetime import datetime
from dataclasses import asdict
import statistics

from .metrics import AdapterMetrics, BaseMetrics, BinanceMetrics, PolymarketMetrics


class MarketMonitor:
    """统一的市场数据监控器"""
    
    def __init__(self):
        self.metrics: Dict[str, AdapterMetrics] = {}
    
    def register_adapter(self, adapter_name: str, exchange_type: str) -> None:
        """注册适配器到监控系统
        
        Args:
            adapter_name: 适配器名称
            exchange_type: 交易所类型
            metrics_type: 指标类型 ('base', 'binance', 'polymarket')
        """
        if adapter_name not in self.metrics:
            self.metrics[adapter_name] = AdapterMetrics(
                adapter_name=adapter_name,
                exchange_type=exchange_type
            )
            print(f"✅ 注册适配器: {adapter_name} ({exchange_type})")
    
    # === 通用监控方法 ===

    def get_metrics(self, adapter_name: str) -> AdapterMetrics:
        """记录延迟"""
        if adapter_name not in self.metrics:
            return None
        
        return self.metrics[adapter_name]
    
    def record_latency(self, adapter_name: str, latency_ms: float) -> None:
        """记录延迟"""
        if adapter_name not in self.metrics:
            return
        
        metrics = self.metrics[adapter_name]
        metrics.latency_ms.append(latency_ms)
        
        # 保持最近数据
        if len(metrics.latency_ms) > 1000:
            metrics.latency_ms.pop(0)
    
    def record_processing_time(self, adapter_name: str, processing_ms: float) -> None:
        """记录处理时间"""
        if adapter_name not in self.metrics:
            return
        
        metrics = self.metrics[adapter_name]
        metrics.processing_ms.append(processing_ms)
        
        if len(metrics.processing_ms) > 1000:
            metrics.processing_ms.pop(0)
    
    def record_connection_status(self, adapter_name: str, is_connected: bool) -> None:
        """记录连接状态"""
        if adapter_name not in self.metrics:
            return
        
        metrics = self.metrics[adapter_name]
        metrics.is_connected = is_connected
        
        if not is_connected:
            metrics.connection_errors += 1   
    
    # === Binance特有监控方法 ===
    
    def record_validation_result(self, adapter_name: str, symbol: str, 
                                is_valid: bool, details: Dict) -> None:
        """记录验证结果（Binance特有）"""
        if adapter_name not in self.metrics:
            return
        
        metrics = self.metrics[adapter_name]
        
        if metrics.is_binance():
            binance_metrics = metrics.data
            binance_metrics.validations_total = details['total_verifications']
            binance_metrics.validations_success = details['passed_verifications']
            binance_metrics.validations_failed = details['failed_verifications']
            binance_metrics.validations_warnings = details['warnings']
            
            # 记录验证时间
            if 'last_verification_time' in details:
                binance_metrics.validation_time.append(details['last_verification_time'])
                if len(binance_metrics.validation_time) > 1000:
                    binance_metrics.validation_time.pop(0)
    
    def record_pending_buffer(self, adapter_name: str, buffer_size: int) -> None:
        """记录pending buffer大小（Binance特有）"""
        if adapter_name not in self.metrics:
            return
        
        metrics = self.metrics[adapter_name]
        
        if metrics.is_binance():
            binance_metrics = metrics.data
            binance_metrics.pending_buffer_sizes.append(buffer_size)
            
            if len(binance_metrics.pending_buffer_sizes) > 1000:
                binance_metrics.pending_buffer_sizes.pop(0)
    
    # === Polymarket特有监控方法 ===
    
    def record_message_stats(self, adapter_name: str, message_type: str, 
                            latency_ms: float) -> None:
        """记录消息统计（Polymarket特有）"""
        if adapter_name not in self.metrics:
            return
        
        metrics = self.metrics[adapter_name]
        
        if metrics.is_polymarket():
            polymarket_metrics = metrics.specific
            polymarket_metrics.update_message_stats(message_type, latency_ms)
            
            # 更新总消息计数
            if message_type == "orderbook":
                polymarket_metrics.orderbook_updates += 1
            elif message_type == "last_trade_price":
                polymarket_metrics.trade_updates += 1
            elif message_type == "price_change":
                polymarket_metrics.price_updates += 1
    
    # === 获取监控数据 ===
    def get_summary(self) -> Dict[str, Any]:
        """获取监控摘要 - 使用统一统计"""
        summary = {}
        
        for adapter_name, metrics in self.metrics.items():
            data = metrics.data
            
            # 基础摘要 - 所有适配器通用
            base_summary = {
                'adapter_type': data.exchange_type.value if hasattr(data.exchange_type, 'value') else str(data.exchange_type),
                'exchange_type': data.exchange_type,
                'is_connected': data.is_connected,
                'connection_errors': data.connection_errors,
                'avg_latency_ms': data.avg_latency,
                'max_latency_ms': data.max_latency,
                'p50_latency_ms': data.p50_latency,
                'p95_latency_ms': data.p95_latency,
                'p99_latency_ms': data.p99_latency,
                'error_rate': data.error_rate,
                'messages_received': data.messages_received,
                'messages_processed': data.messages_processed,
                'errors': data.errors,
                'subscribed_symbols': data.subscribed_symbols,
                'success_rate': 1.0 - data.error_rate,
            }
            
            # Binance特有指标
            if metrics.is_binance():
                base_summary.update({
                    'adapter_type': 'binance',
                    'validation_success_rate': data.validation_success_rate,
                    'avg_pending_buffer': data.avg_pending_buffer,
                    'validations_total': data.validations_total,
                    'validations_success': data.validations_success,
                    'validations_failed': data.validations_failed,
                    'warnings': data.validations_warnings,
                })
            
            # Polymarket特有指标
            elif metrics.is_polymarket():
                base_summary.update({
                    'adapter_type': 'polymarket',
                })
            
            # 添加详细的消息统计
            if hasattr(data, 'message_stats'):
                for key, stat in data.message_stats.items():
                    if stat.count > 0:
                        base_summary[f'{key}_count'] = stat.count
                        base_summary[f'{key}_latency_ewma'] = stat.latency_ewma
            
            summary[adapter_name] = base_summary
        
        return summary
    
    def get_detailed_metrics(self, adapter_name: str) -> Optional[Dict[str, Any]]:
        """获取详细指标"""
        if adapter_name not in self.metrics:
            return None
        
        metrics = self.metrics[adapter_name]
        result = asdict(metrics.data)
        
        # 添加特有指标
        if metrics.is_binance():
            result['binance_specific'] = asdict(metrics.data)
        elif metrics.is_polymarket():
            result['polymarket_specific'] = asdict(metrics.data)
        
        return result