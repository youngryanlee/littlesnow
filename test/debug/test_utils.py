import asyncio
import time
from typing import List, Dict, Any

class ConnectionMonitor:
    """连接监控器"""
    
    def __init__(self):
        self.connection_events = []
        self.data_received = []
        self.start_time = time.time()
    
    def log_connection(self, adapter_name: str, connected: bool):
        """记录连接事件"""
        event = {
            'timestamp': time.time(),
            'adapter': adapter_name,
            'connected': connected,
            'elapsed': time.time() - self.start_time
        }
        self.connection_events.append(event)
        print(f"[{event['elapsed']:.1f}s] {adapter_name} {'连接成功' if connected else '断开连接'}")
    
    def log_data(self, data):
        """记录数据接收"""
        data_point = {
            'timestamp': time.time(),
            'symbol': data.symbol,
            'exchange': data.exchange.value,
            'elapsed': time.time() - self.start_time
        }
        self.data_received.append(data_point)
        
        # 每10条数据打印一次统计
        if len(self.data_received) % 10 == 0:
            print(f"[{data_point['elapsed']:.1f}s] 已接收 {len(self.data_received)} 条数据")
    
    def get_summary(self) -> Dict[str, Any]:
        """获取测试摘要"""
        duration = time.time() - self.start_time
        exchanges = set([d['exchange'] for d in self.data_received])
        symbols = set([d['symbol'] for d in self.data_received])
        
        return {
            'duration_seconds': duration,
            'total_data_received': len(self.data_received),
            'data_rate_per_second': len(self.data_received) / duration if duration > 0 else 0,
            'exchanges': list(exchanges),
            'symbols': list(symbols),
            'connection_events': len(self.connection_events)
        }