# src/market/monitor/dashboard.py
import asyncio
import websockets
import json
from typing import Dict
from datetime import datetime

class MonitorDashboard:
    """监控仪表板 - WebSocket推送监控数据"""
    
    def __init__(self, monitor: MarketMonitor, host: str = "localhost", port: int = 8765):
        self.monitor = monitor
        self.host = host
        self.port = port
        self.clients = set()
        
    async def serve(self):
        """启动WebSocket服务器"""
        async with websockets.serve(self.handle_client, self.host, self.port):
            await asyncio.Future()  # 永久运行
    
    async def handle_client(self, websocket, path):
        """处理客户端连接"""
        self.clients.add(websocket)
        try:
            # 每秒推送一次监控数据
            while True:
                data = self.monitor.get_summary()
                data['timestamp'] = datetime.now().isoformat()
                await websocket.send(json.dumps(data, default=str))
                await asyncio.sleep(1)
        except websockets.ConnectionClosed:
            pass
        finally:
            self.clients.remove(websocket)