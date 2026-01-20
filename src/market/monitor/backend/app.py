# src/market/monitor/backend/app.py
"""
纯粹的WebSocket服务器 - 不包含任何业务逻辑
"""
import asyncio
import json
import logging
from typing import Dict, Set
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
import uuid
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

class ConnectionManager:
    """WebSocket连接管理器 - 纯通信层"""
    
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}
        self.subscriptions: Dict[str, Set[str]] = {}  # 客户端订阅的频道
        
    async def connect(self, websocket: WebSocket) -> str:
        """建立WebSocket连接"""
        await websocket.accept()
        client_id = str(uuid.uuid4())
        self.active_connections[client_id] = websocket
        self.subscriptions[client_id] = set()
        
        logger.info(f"✅ 新客户端连接: {client_id}")
        return client_id
    
    def disconnect(self, client_id: str):
        """断开连接"""
        if client_id in self.active_connections:
            del self.active_connections[client_id]
        if client_id in self.subscriptions:
            del self.subscriptions[client_id]
        logger.info(f"❌ 客户端断开: {client_id}")
    
    async def broadcast(self, data: dict):
        """广播数据到所有订阅了相应频道的客户端"""
        if not self.active_connections:
            return
        
        data_json = json.dumps(data)
        disconnected = []
        
        for client_id, connection in self.active_connections.items():
            try:
                # 检查客户端是否订阅了相关频道
                if self._should_send_to_client(client_id, data):
                    await connection.send_text(data_json)
            except Exception as e:
                logger.error(f"发送到客户端 {client_id} 失败: {e}")
                disconnected.append(client_id)
        
        # 清理断开连接的客户端
        for client_id in disconnected:
            self.disconnect(client_id)
    
    def _should_send_to_client(self, client_id: str, data: dict) -> bool:
        """检查是否应该发送数据给客户端"""
        # 默认发送所有数据，可以按频道过滤
        return True
    
    def subscribe(self, client_id: str, channel: str):
        """客户端订阅频道"""
        if client_id in self.subscriptions:
            self.subscriptions[client_id].add(channel)
    
    def unsubscribe(self, client_id: str, channel: str):
        """客户端取消订阅"""
        if client_id in self.subscriptions:
            self.subscriptions[client_id].discard(channel)

# 全局连接管理器
connection_manager = ConnectionManager()

# FastAPI应用
app = FastAPI(title="Market Monitor WebSocket Server")

# 挂载前端静态文件
BASE_DIR = Path(__file__).parent.parent
frontend_path = BASE_DIR / "frontend"
if frontend_path.exists():
    app.mount("/static", StaticFiles(directory=str(frontend_path)), name="static")
else:
    logger.warning(f"前端目录不存在: {frontend_path}")

# API端点
@app.get("/")
async def get_index():
    """返回前端页面"""
    index_file = frontend_path / "index.html"
    if index_file.exists():
        return FileResponse(str(index_file))
    return JSONResponse(
        content={"error": "前端文件不存在"},
        status_code=404
    )

@app.get("/api/status")
async def get_status():
    """获取服务状态"""
    return {
        "status": "running",
        "connected_clients": len(connection_manager.active_connections),
        "timestamp": datetime.now().isoformat()
    }

@app.get("/api/health")
async def health_check():
    """健康检查"""
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}

# WebSocket端点
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket连接处理"""
    client_id = await connection_manager.connect(websocket)
    
    try:
        # 发送连接确认
        await websocket.send_json({
            "type": "connected",
            "client_id": client_id,
            "timestamp": datetime.now().isoformat()
        })
        
        # 监听客户端消息
        while True:
            try:
                data = await websocket.receive_json()
                
                # 处理客户端消息
                if data.get("type") == "ping":
                    await websocket.send_json({"type": "pong"})
                elif data.get("type") == "subscribe":
                    channel = data.get("channel", "metrics")
                    connection_manager.subscribe(client_id, channel)
                    await websocket.send_json({
                        "type": "subscribed",
                        "channel": channel
                    })
                elif data.get("type") == "unsubscribe":
                    channel = data.get("channel", "metrics")
                    connection_manager.unsubscribe(client_id, channel)
                    await websocket.send_json({
                        "type": "unsubscribed",
                        "channel": channel
                    })
                
            except Exception as e:
                logger.error(f"处理客户端消息失败: {e}")
                break
                
    except WebSocketDisconnect:
        logger.info(f"客户端断开连接: {client_id}")
    except Exception as e:
        logger.error(f"WebSocket错误: {e}")
    finally:
        connection_manager.disconnect(client_id)

# 提供给外部推送数据的接口
@app.post("/api/push/metrics")
async def push_metrics(data: dict):
    """
    外部服务推送监控数据到WebSocket服务器
    供 MonitorService 调用
    """
    try:
        # 确保数据格式正确
        if "type" not in data:
            data["type"] = "metrics_update"
        if "timestamp" not in data:
            data["timestamp"] = datetime.now().isoformat()
        
        # 广播数据到所有客户端
        await connection_manager.broadcast(data)
        
        return {
            "status": "success",
            "message": "数据已广播",
            "clients_count": len(connection_manager.active_connections)
        }
        
    except Exception as e:
        logger.error(f"推送数据失败: {e}")
        return JSONResponse(
            status_code=500,
            content={"status": "error", "message": str(e)}
        )

@app.post("/api/push/test_complete")
async def push_test_complete(message: str = "测试完成"):
    """推送测试完成消息"""
    data = {
        "type": "test_complete",
        "message": message,
        "timestamp": datetime.now().isoformat()
    }
    await connection_manager.broadcast(data)
    return {"status": "success"}

@app.post("/api/push/status")
async def push_status(status_data: dict):
    """推送状态更新"""
    if "type" not in status_data:
        status_data["type"] = "status"
    await connection_manager.broadcast(status_data)
    return {"status": "success"}

@app.get("/api/health")
async def health_check():
    """健康检查端点"""
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )