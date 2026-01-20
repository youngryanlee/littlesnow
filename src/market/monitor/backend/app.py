import asyncio
import os
import sys
from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, BackgroundTasks
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import logging
from typing import Dict, Any
from datetime import datetime

# 设置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 获取项目根目录
current_file = Path(__file__).resolve()
logger.info(f"当前文件: {current_file}")

# 根据你的项目结构：littlesnow/src/market/monitor/backend/app.py
# 我们需要定位到 littlesnow/src
project_root = current_file.parent.parent.parent.parent.parent  # 到littlesnow目录
src_path = project_root / "src"
logger.info(f"项目根目录: {project_root}")
logger.info(f"src目录: {src_path}")

# 将src目录添加到Python路径
if str(src_path) not in sys.path:
    sys.path.insert(0, str(src_path))
    logger.info(f"已添加路径: {src_path}")

# 验证能否导入market模块
try:
    import market
    logger.info("✅ 成功导入market模块")
except ImportError as e:
    logger.error(f"❌ 无法导入market模块: {e}")
    logger.info(f"当前Python路径: {sys.path[:3]}")

BASE_DIR = Path(__file__).parent.parent  # 指向 monitor/ 目录
logger.info(f"BASE_DIR: {BASE_DIR}")    

# WebSocket连接管理器
class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}
        
    async def connect(self, websocket: WebSocket, client_id: str):
        await websocket.accept()
        self.active_connections[client_id] = websocket
        logger.info(f"新的WebSocket连接: {client_id}, 当前连接数: {len(self.active_connections)}")
        
    def disconnect(self, client_id: str):
        if client_id in self.active_connections:
            del self.active_connections[client_id]
            logger.info(f"WebSocket断开: {client_id}, 当前连接数: {len(self.active_connections)}")
    
    async def send_personal_message(self, message: Any, client_id: str):
        if client_id in self.active_connections:
            try:
                await self.active_connections[client_id].send_json(message)
            except:
                self.disconnect(client_id)
    
    async def broadcast(self, message: dict):
        """广播数据到所有客户端"""
        disconnected = []
        
        logger.info(f"开始广播到 {len(self.active_connections)} 个客户端")
        
        for client_id, connection in self.active_connections.items():
            try:
                # 发送消息
                await connection.send_json(message)
                logger.debug(f"✅ 消息发送到客户端 {client_id}")
                
            except WebSocketDisconnect:
                logger.warning(f"客户端 {client_id} 断开连接")
                disconnected.append(client_id)
            except Exception as e:
                logger.error(f"发送消息到客户端 {client_id} 失败: {e}")
                disconnected.append(client_id)
        
        # 清理断开连接的客户端
        for client_id in disconnected:
            self.disconnect(client_id)
        
        logger.info(f"广播完成，清理了 {len(disconnected)} 个断开连接的客户端")
    
    def get_connected_clients(self):
        return list(self.active_connections.keys())

# 全局状态
class GlobalState:
    def __init__(self):
        self.test_running = False
        self.test_task = None
        self.test_summary = {}
        self.test_history = []

state = GlobalState()
manager = ConnectionManager()

# 压力测试运行器
async def run_stress_test(duration_hours: float = 1.0):
    """运行压力测试"""
    logger.info(f"🎬 ===== 开始运行压力测试，时长: {duration_hours}小时 =====")
    
    try:
        state.test_running = True
        logger.info(f"✅ 设置 test_running = True")
        
        # 导入并运行测试
        try:
            from market.monitor.collector import MarketMonitor
            from market.adapter.binance_adapter import BinanceAdapter
            from market.adapter.polymarket_adapter import PolymarketAdapter
            from market.service.ws_manager import WebSocketManager
            logger.info("✅ 成功导入市场监控模块")
        except ImportError as e:
            logger.error(f"❌ 导入模块失败: {e}", exc_info=True)
            state.test_running = False
            return
        
        # 创建监控器
        try:
            monitor = MarketMonitor()
            logger.info("✅ 监控器创建完成")
        except Exception as e:
            logger.error(f"❌ 创建监控器失败: {e}", exc_info=True)
            state.test_running = False
            return
        
        # 创建适配器
        logger.info("创建适配器...")
        try:
            binance = BinanceAdapter()
            polymarket = PolymarketAdapter()
            logger.info("✅ 适配器创建成功")
        except Exception as e:
            logger.error(f"❌ 创建适配器失败: {e}", exc_info=True)
            state.test_running = False
            return
        
        # 设置监控器
        try:
            binance.set_monitor(monitor)
            polymarket.set_monitor(monitor)
            logger.info("✅ 监控器设置完成")
        except Exception as e:
            logger.error(f"❌ 设置监控器失败: {e}", exc_info=True)
        
        # 注册适配器
        try:
            monitor.register_adapter('binance', binance)
            monitor.register_adapter('polymarket', polymarket)
            logger.info("✅ 适配器注册完成")
        except Exception as e:
            logger.error(f"❌ 注册适配器失败: {e}", exc_info=True)
        
        # 创建WebSocket管理器
        logger.info("创建WebSocket管理器...")
        try:
            ws_manager = WebSocketManager()
            ws_manager.register_adapter('binance', binance)
            ws_manager.register_adapter('polymarket', polymarket)
            logger.info("✅ WebSocket管理器创建完成")
        except Exception as e:
            logger.error(f"❌ 创建WebSocket管理器失败: {e}", exc_info=True)
            state.test_running = False
            return
        
        # 启动连接
        logger.info("启动市场数据连接...")
        try:
            await ws_manager.start()
            await asyncio.sleep(3)  # 等待连接建立
            logger.info("✅ 市场数据连接启动成功")
        except Exception as e:
            logger.error(f"❌ 启动市场数据连接失败: {e}", exc_info=True)
            state.test_running = False
            return
        
        # 订阅交易对
        logger.info("订阅交易对...")
        try:
            binance_symbols = ['BTCUSDT', 'ETHUSDT']
            await binance.subscribe(binance_symbols)
            logger.info(f"✅ 已订阅Binance交易对: {binance_symbols}")
        except Exception as e:
            logger.error(f"❌ 订阅Binance交易对失败: {e}", exc_info=True)
        
        # 运行测试
        import time
        from datetime import datetime
        start_time = time.time()
        total_seconds = duration_hours * 3600
        
        logger.info(f"压力测试循环开始，总时长: {total_seconds}秒")
        logger.info(f"活跃的WebSocket客户端: {len(manager.active_connections)}")
        
        loop_count = 0
        while state.test_running and time.time() - start_time < total_seconds:
            try:
                loop_count += 1
                
                # 获取监控数据
                summary = monitor.get_summary()
                
                if loop_count % 10 == 1:  # 每10次循环打印一次
                    logger.info(f"第 {loop_count} 次循环 - 适配器数量: {len(summary)}")
                
                # 确保summary不为空，如果没有数据使用占位数据
                if not summary:
                    logger.debug("监控数据为空，使用占位数据")
                    summary = {
                        'binance': {
                            'avg_latency_ms': 0,
                            'success_rate': 0,
                            'messages_received': 0,
                            'is_connected': False,
                            'adapter_type': 'binance'
                        },
                        'polymarket': {
                            'avg_latency_ms': 0,
                            'success_rate': 0,
                            'messages_received': 0,
                            'is_connected': False,
                            'adapter_type': 'polymarket'
                        }
                    }
                
                # 转换为可序列化的格式
                serializable_summary = {}
                for adapter, metrics in summary.items():
                    serializable_summary[adapter] = {}
                    for k, v in metrics.items():
                        if isinstance(v, (str, int, float, bool, type(None))):
                            serializable_summary[adapter][k] = v
                        elif hasattr(v, '__name__'):  # 处理函数等对象
                            serializable_summary[adapter][k] = v.__name__
                        else:
                            try:
                                serializable_summary[adapter][k] = str(v)
                            except:
                                serializable_summary[adapter][k] = f"无法序列化: {type(v)}"
                
                # 更新状态
                state.test_summary = serializable_summary
                
                # 记录到历史
                state.test_history.append({
                    'timestamp': datetime.now().isoformat(),
                    'summary': serializable_summary
                })
                
                # 广播数据
                broadcast_message = {
                    'type': 'metrics_update',
                    'timestamp': datetime.now().isoformat(),
                    'data': {
                        'summary': serializable_summary,
                        'test_info': {
                            'duration_hours': duration_hours,
                            'elapsed_hours': (time.time() - start_time) / 3600,
                            'status': 'running',
                            'start_time': start_time
                        }
                    }
                }
                
                # 记录关键指标
                if serializable_summary:
                    for adapter, metrics in serializable_summary.items():
                        if loop_count % 20 == 1:  # 每20次循环打印一次详细日志
                            latency = metrics.get('avg_latency_ms', 0)
                            success = metrics.get('success_rate', 0) * 100
                            logger.info(f"📊 {adapter} - 延迟: {latency}ms, 成功率: {success:.1f}%")
                
                # 广播数据
                await manager.broadcast(broadcast_message)
                
                await asyncio.sleep(1)  # 每秒更新一次
                
            except Exception as e:
                logger.error(f"❌ 测试循环出错: {e}", exc_info=True)
                await asyncio.sleep(5)
        
        # 测试完成
        logger.info("🎉 压力测试完成")
        await manager.broadcast({
            'type': 'test_complete',
            'timestamp': datetime.now().isoformat(),
            'message': f'压力测试已完成，运行时长: {duration_hours}小时'
        })
        
        # 清理资源
        logger.info("清理资源...")
        try:
            await ws_manager.stop()
            logger.info("✅ 资源清理完成")
        except Exception as e:
            logger.error(f"清理资源失败: {e}")
        
    except Exception as e:
        logger.error(f"❌ 压力测试失败: {e}", exc_info=True)
        import traceback
        traceback.print_exc()
    finally:
        state.test_running = False
        state.test_task = None
        logger.info(f"📝 最终状态: test_running = {state.test_running}, test_task = {state.test_task}")

# FastAPI应用生命周期
@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    logger.info("启动市场监控服务...")
    yield
    logger.info("停止市场监控服务...")
    # 清理所有WebSocket连接
    for client_id in list(manager.active_connections.keys()):
        manager.disconnect(client_id)
    # 停止测试任务
    if state.test_task:
        state.test_running = False
        try:
            await state.test_task
        except:
            pass

app = FastAPI(lifespan=lifespan)

# 挂载静态文件
frontend_path = BASE_DIR / "frontend"
app.mount("/static", StaticFiles(directory=str(frontend_path)), name="static")

# API端点
@app.get("/")
async def get_index():
    """返回前端页面"""
    index_file = frontend_path / "index.html"
    return FileResponse(str(index_file))

@app.get("/api/status")
async def get_status():
    """获取服务状态"""
    return {
        "status": "running",
        "test_running": state.test_running,
        "connected_clients": len(manager.active_connections)
    }

@app.get("/api/test/history")
async def get_test_history():
    """获取测试历史数据"""
    return {
        "history": state.test_history[-100:],  # 返回最近100条记录
        "count": len(state.test_history)
    }

from fastapi.responses import JSONResponse  # 需要导入这个

@app.post("/api/test/start")
async def start_test(duration_hours: float = 1.0):
    """开始压力测试"""
    logger.info(f"接收到开始测试请求，时长: {duration_hours}小时")
    logger.info(f"当前测试状态: running={state.test_running}, task={state.test_task}")
    
    if state.test_running:
        logger.warning("测试已在运行中")
        return JSONResponse(
            status_code=400,
            content={"status": "error", "message": "测试已在运行中"}
        )
    
    try:
        logger.info("创建测试任务...")
        # 关键修改：使用 asyncio.create_task 在后台运行
        state.test_running = True
        state.test_task = asyncio.create_task(run_stress_test(duration_hours))
        
        logger.info(f"压力测试任务已创建，task_id: {id(state.test_task)}")
        
        # 立即发送状态更新给所有客户端
        await manager.broadcast({
            'type': 'status',
            'test_running': True,
            'message': f'压力测试已开始，时长: {duration_hours}小时',
            'timestamp': datetime.now().isoformat()
        })
        
        return {
            "status": "success", 
            "message": f"压力测试已开始，时长: {duration_hours}小时",
            "task_created": True
        }
        
    except Exception as e:
        logger.error(f"创建测试任务失败: {e}", exc_info=True)
        state.test_running = False
        state.test_task = None
        return JSONResponse(
            status_code=500,
            content={"status": "error", "message": f"启动测试失败: {str(e)}"}
        )

@app.post("/api/test/stop")
async def stop_test():
    """停止压力测试"""
    if not state.test_running:
        return {"status": "error", "message": "测试未在运行"}
    
    state.test_running = False
    if state.test_task:
        try:
            await state.test_task
        except:
            pass
        state.test_task = None
    
    return {"status": "success", "message": "压力测试已停止"}

# WebSocket端点
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    import uuid
    client_id = str(uuid.uuid4())
    
    await manager.connect(websocket, client_id)
    
    try:
        # 发送当前状态
        await manager.send_personal_message({
            'type': 'status',
            'test_running': state.test_running,
            'summary': state.test_summary
        }, client_id)
        
        # 保持连接活跃
        while True:
            data = await websocket.receive_json()
            # 处理客户端消息
            if data.get('type') == 'ping':
                await manager.send_personal_message({'type': 'pong'}, client_id)
            elif data.get('type') == 'get_summary':
                await manager.send_personal_message({
                    'type': 'summary',
                    'summary': state.test_summary
                }, client_id)
                
    except WebSocketDisconnect:
        manager.disconnect(client_id)

@app.get("/api/metrics")
async def get_metrics():
    """获取当前监控指标"""
    try:
        # 确保有数据返回
        summary = state.test_summary
        
        # 如果没有数据，返回空结构
        if not summary:
            summary = {
                'binance': {
                    'avg_latency_ms': 0,
                    'success_rate': 0,
                    'messages_received': 0,
                    'is_connected': False,
                    'last_update': datetime.now().isoformat()
                },
                'polymarket': {
                    'avg_latency_ms': 0,
                    'success_rate': 0,
                    'messages_received': 0,
                    'is_connected': False,
                    'last_update': datetime.now().isoformat()
                }
            }
        
        return {
            "status": "success",
            "summary": summary,
            "test_running": state.test_running,
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        logger.error(f"获取指标失败: {e}")
        return JSONResponse(
            status_code=500,
            content={
                "status": "error",
                "message": f"获取指标失败: {str(e)}"
            }
        )        

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )