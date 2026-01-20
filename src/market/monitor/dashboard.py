# src/market/monitor/dashboard.py
import streamlit as st
import asyncio
import json
import time
from datetime import datetime
import pandas as pd
import plotly.graph_objects as go
from typing import Dict, Any, Optional, List
import threading
from collections import defaultdict, deque
import websockets
import aiohttp
from concurrent.futures import ThreadPoolExecutor
import logging

# 配置 logging，确保输出到控制台
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),  # 输出到控制台
        logging.FileHandler('dashboard.log')  # 同时输出到文件
    ]
)

logger = logging.getLogger("dashboard")

class WebSocketMonitorClient:
    """WebSocket监控器客户端"""
    
    def __init__(self, uri: str = "ws://localhost:9999/ws"):
        logger.info("init WebSocketMonitorClient")
        self.uri = uri
        self.websocket = None
        self.connected = False
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = 5
        self.reconnect_delay = 1  # 秒
        self.latest_data = {}
        self.callbacks = []
        self.running = False
        self.thread = None
        
    def add_callback(self, callback):
        """添加数据回调函数"""
        self.callbacks.append(callback)
    
    def remove_callback(self, callback):
        """移除数据回调函数"""
        if callback in self.callbacks:
            self.callbacks.remove(callback)
        
    async def connect(self):
        """连接到WebSocket服务器"""
        try:
            # 清除代理环境变量
            import os
            proxy_env_vars = [
                'HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY',
                'http_proxy', 'https_proxy', 'all_proxy'
            ]
            old_proxies = {}
            for var in proxy_env_vars:
                if var in os.environ:
                    old_proxies[var] = os.environ[var]
                    del os.environ[var]

            # 明确指定不使用代理
            self.websocket = await websockets.connect(
                self.uri, 
                proxy=None,  # 关键：明确禁用代理
                ping_interval=None  # 可选：禁用自动ping
            )

            # 恢复代理环境变量
            for var, value in old_proxies.items():
                os.environ[var] = value
                
            self.connected = True
            self.reconnect_attempts = 0
            logger.info(f"Connected to WebSocket server: {self.uri}")
            return True
        except Exception as e:
            logger.error(f"Failed to connect to WebSocket server: {e}")
            return False    
    
    async def disconnect(self):
        """断开连接"""
        self.connected = False
        if self.websocket:
            await self.websocket.close()
            self.websocket = None
    
    async def send_message(self, message: Dict):
        """发送消息到服务器"""
        if self.connected and self.websocket:
            try:
                logger.info("send_message: ", message)
                await self.websocket.send(json.dumps(message))
            except Exception as e:
                logger.exception(f"Failed to send message: {e}")
                self.connected = False
    
    async def receive_messages(self):
        """接收消息"""
        logger.info(f"[WebSocketClient receive_messages] 开始接收消息，连接状态: {self.connected}")
        logger.info(f"[WebSocketClient receive_messages] websocket对象: {self.websocket}")
    
        
        while self.connected and self.running:
            try:
                message = await self.websocket.recv()
                logger.info(f"[WebSocketClient receive_messages] 收到原始消息，长度: {len(message)}")
                logger.info(f"[WebSocketClient receive_messages] 消息前100字符: {message[:100]}")
                
                data = json.loads(message)
                logger.info(f"[WebSocketClient receive_messages] 解析JSON成功，类型: {data.get('type')}")
                
                # 更新最新数据
                self.latest_data = data
                
                # 调用所有回调函数
                logger.info(f"[WebSocketClient receive_messages] 调用{len(self.callbacks)}个回调函数")
                for callback in self.callbacks:
                    try:
                        callback(data)
                    except Exception as e:
                        logger.info(f"[WebSocketClient receive_messages] 回调函数错误: {e}")
                        logger.exception(f"Callback error: {e}")
                        
            except websockets.exceptions.ConnectionClosed:
                logger.info(f"[WebSocketClient receive_messages] WebSocket连接关闭")
                logger.exception("WebSocket connection closed")
                self.connected = False
                break
            except Exception as e:
                logger.info(f"[WebSocketClient receive_messages] 接收消息错误: {e}")
                logger.exception(f"Error receiving message: {e}")
                self.connected = False
    
    async def _reconnect(self):
        """重新连接"""
        while self.running and not self.connected and self.reconnect_attempts < self.max_reconnect_attempts:
            logger.debug(f"Attempting to reconnect ({self.reconnect_attempts + 1}/{self.max_reconnect_attempts})...")
            self.reconnect_attempts += 1
            
            if await self.connect():
                # 重新连接成功，开始接收消息
                asyncio.create_task(self.receive_messages())
                return True
            
            # 等待一段时间后重试
            await asyncio.sleep(self.reconnect_delay * self.reconnect_attempts)
        
        if self.reconnect_attempts >= self.max_reconnect_attempts:
            logger.debug("Max reconnection attempts reached")
        
        return False
    
    def start(self):
        logger.info("start: ")
        """启动客户端（在后台线程中运行）"""
        if self.running:
            return
        logger.info("start success: ")
        self.running = True
        self.thread = threading.Thread(target=self._run_in_thread, daemon=True)
        self.thread.start()
    
    def stop(self):
        """停止客户端"""
        self.running = False
        if self.thread:
            self.thread.join(timeout=2)
    
    def _run_in_thread(self):
        """在线程中运行异步事件循环"""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            # 连接并运行
            loop.run_until_complete(self._run())
        except Exception as e:
            logger.exception(f"WebSocket client error: {e}")
        finally:
            loop.close()     
    
    async def _run(self):
        """运行客户端"""
        logger.info(f"[WebSocketClient _run] 开始运行，URI: {self.uri}")
        
        # 初始连接
        if not await self.connect():
            logger.info(f"[WebSocketClient _run] 初始连接失败")
            logger.debug("Initial connection failed")
            return
        
        logger.info(f"[WebSocketClient _run] 连接成功")
        
        # 开始接收消息
        receive_task = asyncio.create_task(self.receive_messages())
        logger.info(f"[WebSocketClient _run] 接收消息任务创建")
        
        # 保持运行
        try:
            while self.running:
                if not self.connected:
                    logger.info(f"[WebSocketClient _run] 连接断开，尝试重连")
                    # 尝试重连
                    if not await self._reconnect():
                        logger.info(f"[WebSocketClient _run] 重连失败，退出循环")
                        break
                await asyncio.sleep(1)
        except Exception as e:
            logger.info(f"[WebSocketClient _run] 运行错误: {e}")
            logger.exception(f"WebSocket client run error: {e}")
        finally:
            logger.info(f"[WebSocketClient _run] 清理任务")
            if receive_task:
                receive_task.cancel()
            await self.disconnect()
            logger.info(f"[WebSocketClient _run] 客户端停止")
    
    def get_summary(self) -> Dict[str, Any]:
        """获取最新的监控摘要"""
        return self.latest_data.get('data', {}).get('summary', {})
    
    def get_test_info(self) -> Dict[str, Any]:
        """获取测试信息"""
        return self.latest_data.get('data', {}).get('test_info', {})
    
    def get_message_type(self) -> str:
        """获取消息类型"""
        return self.latest_data.get('type', '')


class HTTPMonitorClient:
    """HTTP监控器客户端（用于获取历史数据）"""
    
    def __init__(self, base_url: str = "http://localhost:9999"):
        self.base_url = base_url
        self.session = None
    
    async def get_summary(self) -> Dict[str, Any]:
        """获取监控摘要"""
        try:
            if not self.session:
                self.session = aiohttp.ClientSession()
            
            async with self.session.get(f"{self.base_url}/api/summary") as response:
                if response.status == 200:
                    return await response.json()
                else:
                    logger.debug(f"HTTP error: {response.status}")
                    return {}
        except Exception as e:
            logger.exception(f"HTTP request error: {e}")
            return {}
    
    async def get_history(self, adapter: str, metric: str, limit: int = 100) -> List:
        """获取历史数据"""
        try:
            if not self.session:
                self.session = aiohttp.ClientSession()
            
            url = f"{self.base_url}/api/history/{adapter}/{metric}?limit={limit}"
            async with self.session.get(url) as response:
                if response.status == 200:
                    return await response.json()
                else:
                    logger.debug(f"HTTP error: {response.status}")
                    return []
        except Exception as e:
            logger.exception(f"HTTP request error: {e}")
            return []
    
    async def close(self):
        """关闭HTTP会话"""
        if self.session:
            await self.session.close()


class WebSocketMonitorServer:
    """WebSocket监控服务器"""
    
    def __init__(self, monitor, host: str = "0.0.0.0", port: int = 9999):
        logger.info("init WebSocketMonitorServer")
        self.monitor = monitor
        self.host = host
        self.port = port
        self.connected_clients = set()
        self.server = None
        self.running = False
        self.broadcast_interval = 1.0  # 秒
        self.broadcast_task = None
        
    async def handler(self, websocket):
        """处理WebSocket连接 - 新版本websockets可能只传递一个参数"""
        # 从websocket对象获取路径（如果有的话）
        path = getattr(websocket, 'path', '/')
        
        # 添加客户端
        self.connected_clients.add(websocket)
        client_address = websocket.remote_address
        logger.info(f"New WebSocket client connected: {client_address}, path: {path}")
        
        try:
            # 发送欢迎消息
            welcome_message = {
                "type": "welcome",
                "timestamp": time.time(),
                "message": f"Connected to monitor server. Clients: {len(self.connected_clients)}"
            }
            await websocket.send(json.dumps(welcome_message))
            
            # 处理客户端消息
            async for message in websocket:
                try:
                    data = json.loads(message)
                    await self.handle_client_message(websocket, data)
                except json.JSONDecodeError:
                    logger.exception(f"Invalid JSON from client {client_address}")
                except Exception as e:
                    logger.exception(f"Error handling message from {client_address}: {e}")
                    
        except websockets.exceptions.ConnectionClosed:
            logger.info(f"WebSocket client disconnected: {client_address}")
        except Exception as e:
            logger.exception(f"Error in handler for {client_address}: {e}")
        finally:
            # 移除客户端
            if websocket in self.connected_clients:
                self.connected_clients.remove(websocket)
            logger.debug(f"Client removed. Remaining clients: {len(self.connected_clients)}")
    
    async def handle_client_message(self, websocket, data: Dict):
        """处理客户端消息"""
        message_type = data.get('type')
        
        if message_type == 'ping':
            # 响应ping
            response = {
                'type': 'pong',
                'timestamp': time.time()
            }
            await websocket.send(json.dumps(response))
            
        elif message_type == 'subscribe':
            # 订阅特定数据
            topics = data.get('topics', [])
            response = {
                'type': 'subscribed',
                'timestamp': time.time(),
                'topics': topics
            }
            await websocket.send(json.dumps(response))
            
        elif message_type == 'command':
            # 处理命令
            command = data.get('command')
            await self.handle_command(websocket, command, data.get('params', {}))
    
    async def handle_command(self, websocket, command: str, params: Dict):
        """处理命令"""
        if command == 'get_summary':
            # 获取当前摘要
            summary = self.monitor.get_summary()
            response = {
                'type': 'command_response',
                'command': command,
                'timestamp': time.time(),
                'data': {
                    'summary': summary
                }
            }
            await websocket.send(json.dumps(response))
        
        elif command == 'test_info':
            # 获取测试信息（如果有的话）
            response = {
                'type': 'command_response',
                'command': command,
                'timestamp': time.time(),
                'data': {
                    'test_info': {
                        'status': 'running',  # 实际应从监控器获取
                        'start_time': time.time() - 3600,  # 示例
                        'duration': 7200  # 示例
                    }
                }
            }
            await websocket.send(json.dumps(response))
    
    async def broadcast_metrics(self):
        """广播监控指标到所有客户端"""
        while self.running:
            try:
                logger.info(f"[WebSocketServer] 广播循环，客户端数量: {len(self.connected_clients)}")
                if self.connected_clients:
                    # 获取监控数据
                    summary = self.monitor.get_summary()

                    logger.info(f"[WebSocketServer] 从监控器获取摘要，长度: {len(summary)}")
                    if summary:
                        logger.info(f"[WebSocketServer] 摘要键: {list(summary.keys())}")
                        for adapter_name, metrics in summary.items():
                            logger.info(f"[WebSocketServer] {adapter_name}: {len(metrics)} 个指标")
                    
                    # 准备广播消息
                    message = {
                        'type': 'metrics_update',
                        'timestamp': time.time(),
                        'data': {
                            'summary': summary
                        }
                    }
                    
                    try:
                        # 使用default=str处理非序列化对象
                        message_json = json.dumps(message, default=str)
                        logger.info(f"[WebSocketServer] JSON消息长度: {len(message_json)}")
                    except Exception as e:
                        logger.exception(f"[WebSocketServer] JSON序列化失败: {e}")
                        await asyncio.sleep(self.broadcast_interval)
                        continue
                    
                    # 发送给所有客户端
                    tasks = []
                    for client in self.connected_clients:
                        try:
                            logger.info(f"[WebSocketServer] 准备向客户端 {client.remote_address} 发送消息")
                            tasks.append(client.send(message_json))
                        except Exception as e:
                            logger.exception(f"Error sending to client: {e}")
                    
                    if tasks:
                        logger.info(f"[WebSocketServer] 向 {len(tasks)} 个客户端发送消息")
                        try:
                            results = await asyncio.gather(*tasks, return_exceptions=True)
                            # 检查发送结果
                            for i, result in enumerate(results):
                                if isinstance(result, Exception):
                                    logger.error(f"[WebSocketServer] 发送到客户端 {i} 失败: {result}")
                                else:
                                    logger.info(f"[WebSocketServer] 消息发送到客户端 {i} 成功")
                        except Exception as e:
                            logger.exception(f"[WebSocketServer] 发送消息时出错: {e}")
                    else:
                        logger.info(f"[WebSocketServer] 没有客户端需要发送")
                
                # 等待下一次广播
                await asyncio.sleep(self.broadcast_interval)
                
            except Exception as e:
                logger.exception(f"Error in broadcast_metrics: {e}")
                await asyncio.sleep(self.broadcast_interval)
    
    async def start(self):
        """启动WebSocket服务器"""
        try:
            logger.info("WebSocketMonitorServer start")
            self.server = await websockets.serve(
                self.handler,
                self.host,
                self.port
            )
            self.running = True
            
            # 启动广播任务
            self.broadcast_task = asyncio.create_task(self.broadcast_metrics())
            
            logger.debug(f"WebSocket monitor server started on ws://{self.host}:{self.port}")
            return True
            
        except Exception as e:
            logger.exception(f"Failed to start WebSocket server: {e}")
            return False
    
    async def stop(self):
        """停止WebSocket服务器"""
        self.running = False
        
        if self.broadcast_task:
            self.broadcast_task.cancel()
        
        if self.server:
            self.server.close()
            await self.server.wait_closed()
        
        # 关闭所有客户端连接
        for client in list(self.connected_clients):
            await client.close()
        
        self.connected_clients.clear()
        logger.debug("WebSocket server stopped")


class MonitorDashboard:
    """Streamlit实时监控仪表板（WebSocket版本）"""
    
    def __init__(self, monitor=None, websocket_uri: str = "ws://localhost:9999/ws"):
        logger.info("init MonitorDashboard")
        # 初始化状态
        self.monitor = monitor
        self.websocket_uri = websocket_uri
        
        # 关键修复：从session state恢复数据，而不是每次都重置
        if 'dashboard_history' in st.session_state:
            # 恢复历史数据
            self.history = st.session_state.dashboard_history
        else:
            self.history = defaultdict(lambda: defaultdict(list))
            
        if 'dashboard_current_summary' in st.session_state:
            # 恢复当前摘要
            self.current_summary = st.session_state.dashboard_current_summary
        else:
            self.current_summary = {}
        
        self.new_data_received = False
        
        # WebSocket客户端
        self.ws_client = WebSocketMonitorClient(websocket_uri)
        self.ws_client.add_callback(self._on_websocket_data)
        
        # HTTP客户端
        self.http_client = HTTPMonitorClient(websocket_uri.replace("ws://", "http://").replace("/ws", ""))
        
        # 控制状态
        self.update_thread = None
        self.running = False
        self.connection_status = "disconnected"
        
        # 初始化Streamlit状态
        self._init_session_state()
    
    def _init_session_state(self):
        """初始化Streamlit session state"""
        if 'dashboard_initialized' not in st.session_state:
            st.session_state.dashboard_initialized = True
            st.session_state.history_length = 100
            st.session_state.selected_adapters = []
            st.session_state.refresh_rate = 5
            st.session_state.ws_connected = False
        
    def _on_websocket_data(self, data: Dict):
        """WebSocket数据回调函数 - 增强版本"""
        logger.info(f"[Dashboard] 收到WebSocket数据: type={data.get('type')}")
        
        message_type = data.get('type')
        
        if message_type == 'metrics_update':
            # 处理监控数据更新
            data_content = data.get('data', {})
            summary = data_content.get('summary', {})
            timestamp = data.get('timestamp', time.time())
            
            logger.info(f"[Dashboard] metrics_update - 摘要长度: {len(summary)}")
            
            # 关键修复：同时更新多个存储位置
            self.current_summary = summary
            st.session_state.current_summary = summary
            st.session_state.dashboard_current_summary = summary  # 新增：持久化存储
            
            # 存储历史数据
            for adapter_name, metrics in summary.items():
                logger.info(f"[Dashboard] 处理适配器: {adapter_name}")
                
                # 确保历史数据结构存在
                if adapter_name not in self.history:
                    self.history[adapter_name] = defaultdict(list)
                
                self.history[adapter_name]['timestamps'].append(timestamp)
                self.history[adapter_name]['avg_latency_ms'].append(metrics.get('avg_latency_ms', 0))
                self.history[adapter_name]['p95_latency_ms'].append(metrics.get('p95_latency_ms', 0))
                self.history[adapter_name]['p99_latency_ms'].append(metrics.get('p99_latency_ms', 0))
                self.history[adapter_name]['messages_received'].append(metrics.get('messages_received', 0))
                self.history[adapter_name]['error_rate'].append(metrics.get('error_rate', 0))
                self.history[adapter_name]['success_rate'].append(metrics.get('success_rate', 0))
                
                # 保持最近1000个数据点
                for key in list(self.history[adapter_name].keys()):
                    if len(self.history[adapter_name][key]) > 1000:
                        self.history[adapter_name][key].pop(0)
            
            # 关键修复：保存历史数据到session state
            st.session_state.dashboard_history = self.history
            
            logger.info(f"[Dashboard] 数据已更新并保存到session state")
            
        elif message_type == 'welcome':
            logger.info(f"[Dashboard] WebSocket欢迎消息: {data.get('message')}")
            self.connection_status = "connected"
            st.session_state.ws_connected = True
            st.session_state.last_connection_time = time.time()
            logger.info(f"[Dashboard] 连接状态更新为: connected") 
    
    def start_monitoring(self):
        """开始监控"""
        logger.info(f"[Dashboard start_monitoring] 开始监控，当前运行状态: {self.running}")
        
        if not self.running:
            # 启动WebSocket客户端
            logger.info(f"[Dashboard start_monitoring] 启动WebSocket客户端，URI: {self.websocket_uri}")
            self.ws_client.start()
            logger.info(f"[Dashboard start_monitoring] WebSocket客户端启动完成")
            
            # 启动后台更新线程
            self.running = True
            logger.info(f"[Dashboard start_monitoring] 设置running=True")
            
            # 等待连接建立
            for i in range(10):
                if self.ws_client.connected:
                    logger.info(f"[Dashboard start_monitoring] 客户端已连接")
                    break
                time.sleep(0.5)
            
            return True
        
        logger.info(f"[Dashboard start_monitoring] 已经在运行，直接返回")
        return True
    
    def stop_monitoring(self):
        """停止监控"""
        self.running = False
        
        # 停止WebSocket客户端
        self.ws_client.stop()
        
        if self.update_thread:
            self.update_thread.join(timeout=2)
        
        self.connection_status = "disconnected"
        st.session_state.ws_connected = False
    
    def _update_loop(self):
        """后台更新循环（用于检查连接状态等）"""
        while self.running:
            try:
                # 检查连接状态
                if self.ws_client.connected:
                    self.connection_status = "connected"
                else:
                    self.connection_status = "disconnected"
                
                time.sleep(1)
            except Exception as e:
                logger.exception(f"Update loop error: {e}")
                time.sleep(5)
    
    def create_dashboard(self):
        """创建Streamlit仪表板 - 增强版本"""
        st.set_page_config(
            page_title="Market Data Monitor (WebSocket)",
            page_icon="📈",
            layout="wide",
            initial_sidebar_state="expanded"
        )
        
        # 页面标题
        st.title("📈 Market Data Real-time Monitor (WebSocket)")
        st.markdown("---")
        
        # 首先检查WebSocket客户端是否正在运行，如果没有则启动
        if not self.ws_client.running:
            logger.info("[Dashboard] WebSocket客户端未运行，正在启动...")
            self.start_monitoring()
        
        # 关键修复：在页面顶部显示连接状态
        connection_col1, connection_col2, connection_col3 = st.columns(3)
        with connection_col1:
            status_color = "green" if self.connection_status == "connected" else "red"
            status_icon = "✅" if self.connection_status == "connected" else "❌"
            st.markdown(f"**连接状态:** {status_icon} **{self.connection_status.capitalize()}**")
        
        with connection_col2:
            if hasattr(st.session_state, 'last_update_time'):
                last_update = datetime.fromtimestamp(st.session_state.last_update_time)
                st.markdown(f"**最后更新:** {last_update.strftime('%H:%M:%S')}")
            else:
                st.markdown("**最后更新:** 无")
        
        with connection_col3:
            st.markdown(f"**客户端运行:** {'✅ 是' if self.ws_client.running else '❌ 否'}")
        
        # 添加调试信息
        with st.sidebar:
            st.subheader("🔍 Debug Info")
            
            # 显示连接状态
            st.write(f"连接状态: {self.connection_status}")
            st.write(f"WebSocket客户端连接: {self.ws_client.connected}")
            st.write(f"客户端运行状态: {self.ws_client.running}")
            
            # 显示数据状态
            summary_from_session = st.session_state.get('current_summary', {})
            st.write(f"Session state摘要长度: {len(summary_from_session)}")
            st.write(f"适配器: {list(summary_from_session.keys())}")
            
            # 显示实例数据
            st.write(f"实例摘要长度: {len(self.current_summary)}")
            st.write(f"实例适配器: {list(self.current_summary.keys())}")
            
            # 检查数据一致性
            if summary_from_session and self.current_summary:
                if summary_from_session != self.current_summary:
                    st.warning("⚠️ Session state和实例数据不一致")
            
            # 手动刷新按钮
            if st.button("🔄 强制刷新", key="force_refresh"):
                # 尝试从WebSocket客户端获取最新数据
                latest_data = self.ws_client.latest_data
                if latest_data and 'data' in latest_data:
                    self._on_websocket_data(latest_data)
                st.rerun()
            
            # 连接控制
            st.markdown("---")
            st.subheader("连接控制")
            
            col1, col2 = st.columns(2)
            with col1:
                if st.button("🔗 重新连接", use_container_width=True):
                    if self.ws_client.connected:
                        self.ws_client.connected = False  # 强制断开
                    time.sleep(0.5)
                    self.start_monitoring()
                    st.success("已尝试重新连接")
                    st.rerun()
            
            with col2:
                if st.button("📊 测试连接", use_container_width=True):
                    if self.ws_client.connected:
                        st.success("连接正常")
                    else:
                        st.error("连接断开")
        
        # 侧边栏配置
        with st.sidebar:
            st.header("⚙️ Configuration")
            
            # WebSocket服务器配置
            st.subheader("WebSocket Server")
            col1, col2 = st.columns(2)
            with col1:
                if st.button("🔗 Connect", use_container_width=True, key="connect_btn_main"):
                    if self.start_monitoring():
                        st.success("Connected to WebSocket server")
                        time.sleep(2)
                        st.rerun()
                    else:
                        st.error("Failed to connect")
            with col2:
                if st.button("🔌 Disconnect", use_container_width=True, key="disconnect_btn_main"):
                    self.stop_monitoring()
                    st.warning("Disconnected")
                    st.rerun()
            
            # WebSocket服务器地址
            new_uri = st.text_input("WebSocket URI", value=self.websocket_uri, key="ws_uri_input")
            if new_uri != self.websocket_uri:
                self.websocket_uri = new_uri
                self.ws_client.uri = new_uri
            
            # 监控控制
            st.markdown("---")
            st.subheader("Monitoring Control")
            
            # 刷新间隔
            refresh_rate = st.slider(
                "Refresh rate (seconds)",
                min_value=1,
                max_value=60,
                value=st.session_state.get('refresh_rate', 5),
                step=1,
                key="refresh_rate_slider_main"
            )
            st.session_state.refresh_rate = refresh_rate
            
            # 历史数据长度
            history_length = st.slider(
                "History points to show",
                min_value=10,
                max_value=500,
                value=st.session_state.get('history_length', 100),
                step=10,
                key="history_length_slider_main"
            )
            st.session_state.history_length = history_length
        
        # 主内容区域 - 改进的数据检查逻辑
        # 使用多级数据源，确保总有数据显示
        display_summary = {}
        
        # 优先级1：最新的WebSocket数据
        if self.current_summary:
            display_summary = self.current_summary
            st.session_state.last_data_source = "current_summary"
        
        # 优先级2：session state中的数据
        elif 'current_summary' in st.session_state and st.session_state.current_summary:
            display_summary = st.session_state.current_summary
            st.session_state.last_data_source = "session_state"
            
            # 同时更新实例数据（保持同步）
            self.current_summary = display_summary
        
        # 优先级3：从WebSocket客户端缓存获取
        elif hasattr(self.ws_client, 'latest_data') and self.ws_client.latest_data:
            latest_data = self.ws_client.latest_data
            if 'data' in latest_data and 'summary' in latest_data['data']:
                display_summary = latest_data['data']['summary']
                st.session_state.last_data_source = "ws_client_cache"
                
                # 更新session state和实例数据
                self.current_summary = display_summary
                st.session_state.current_summary = display_summary
        
        # 获取适配器列表
        adapter_names = list(display_summary.keys()) if display_summary else []
        
        if adapter_names:
            # 显示数据预览
            with st.expander("📊 数据预览", expanded=True):
                for adapter in adapter_names:
                    if adapter in display_summary:
                        metrics = display_summary[adapter]
                        st.write(f"**{adapter}:**")
                        if isinstance(metrics, dict):
                            col1, col2, col3 = st.columns(3)
                            with col1:
                                latency = metrics.get('avg_latency_ms', 0)
                                st.metric("平均延迟", f"{latency:.1f}ms")
                            with col2:
                                success = metrics.get('success_rate', 0) * 100
                                st.metric("成功率", f"{success:.1f}%")
                            with col3:
                                messages = metrics.get('messages_received', 0)
                                st.metric("消息数", f"{messages}")
                        else:
                            st.write(f"指标类型: {type(metrics)}")
            
            tab1, tab2, tab3, tab4 = st.tabs([
                "📊 Overview", 
                "📈 Latency Charts", 
                "📋 Detailed Metrics",
                "🔧 Control"
            ])
            
            with tab1:
                self._create_overview_tab(display_summary, adapter_names)
            
            with tab2:
                self._create_latency_charts_tab(adapter_names, history_length)
            
            with tab3:
                self._create_detailed_metrics_tab(display_summary, adapter_names)
            
            with tab4:
                self._create_control_tab()
                
            # 显示数据源信息（调试用）
            if 'last_data_source' in st.session_state:
                source_info = {
                    "current_summary": "实时WebSocket数据",
                    "session_state": "缓存数据",
                    "ws_client_cache": "客户端缓存"
                }
                source = st.session_state.last_data_source
                st.caption(f"数据来源: {source_info.get(source, source)}")
                
        else:
            # 显示"No adapters available"时的改进界面
            st.warning("No adapters available. Please connect to WebSocket server and ensure adapters are running.")
            
            # 提供更多帮助信息
            help_col1, help_col2 = st.columns(2)
            
            with help_col1:
                with st.expander("🔍 诊断信息", expanded=True):
                    st.write(f"连接状态: {self.connection_status}")
                    st.write(f"WebSocket连接: {self.ws_client.connected}")
                    st.write(f"客户端运行: {self.ws_client.running}")
                    
                    # 检查最近一次数据接收时间
                    if hasattr(st.session_state, 'last_update_time'):
                        elapsed = time.time() - st.session_state.last_update_time
                        st.write(f"距上次更新: {elapsed:.1f}秒")
                    
                    # 显示缓存数据状态
                    if 'current_summary' in st.session_state:
                        cached_adapters = list(st.session_state.current_summary.keys())
                        st.write(f"缓存适配器: {cached_adapters}")
            
            with help_col2:
                with st.expander("🛠️ 修复建议", expanded=True):
                    st.markdown("""
                    1. **检查WebSocket服务器是否运行**
                    - 确保压力测试正在运行
                    - 检查端口9999是否被占用
                    
                    2. **尝试重新连接**
                    - 点击侧边栏的"重新连接"按钮
                    - 或点击"Connect"按钮
                    
                    3. **检查网络连接**
                    - 确保本地网络正常
                    - 检查防火墙设置
                    
                    4. **查看日志**
                    - 检查`dashboard.log`文件
                    - 查看控制台输出
                    """)
            
            # 立即尝试重新连接
            if st.button("🔄 立即尝试重新连接并刷新", type="primary"):
                if not self.ws_client.running:
                    self.start_monitoring()
                time.sleep(1)
                st.rerun()
        
        # 自动刷新 - 添加更智能的逻辑
        time.sleep(refresh_rate)
        
        # 只有在连接正常时才自动刷新
        if self.ws_client.connected:
            st.rerun()
        else:
            # 如果连接断开，等待更长时间再尝试刷新
            time.sleep(3)
            st.rerun()
    
    def _create_overview_tab(self, summary: Dict, selected_adapters: list):
        """创建概览标签页"""
        cols = st.columns(len(selected_adapters))
        
        for idx, adapter_name in enumerate(selected_adapters):
            with cols[idx]:
                metrics = summary.get(adapter_name, {})
                
                # 适配器卡片
                st.markdown(f"### {adapter_name.upper()}")
                
                # 连接状态
                is_connected = metrics.get('is_connected', False)
                status_icon = "✅" if is_connected else "❌"
                
                st.markdown(f"**Status:** {status_icon} {'Connected' if is_connected else 'Disconnected'}")
                
                # 关键指标
                col1, col2, col3 = st.columns(3)
                
                with col1:
                    avg_latency = metrics.get('avg_latency_ms', 0)
                    st.metric(
                        "Avg Latency",
                        f"{avg_latency:.1f}ms",
                        delta=None,
                        delta_color="normal",
                        help="Average network latency"
                    )
                
                with col2:
                    success_rate = metrics.get('success_rate', 0) * 100
                    st.metric(
                        "Success Rate",
                        f"{success_rate:.1f}%",
                        delta=None,
                        delta_color="normal",
                        help="Message processing success rate"
                    )
                
                with col3:
                    messages = metrics.get('messages_received', 0)
                    st.metric(
                        "Messages",
                        f"{messages}",
                        delta=None,
                        delta_color="normal",
                        help="Total messages received"
                    )
                
                # 延迟状态指示器
                self._latency_indicator(avg_latency)
                
                # 订阅信息
                subscribed_symbols = metrics.get('subscribed_symbols', [])
                if subscribed_symbols:
                    with st.expander(f"Subscribed Symbols ({len(subscribed_symbols)})"):
                        for symbol in subscribed_symbols[:10]:
                            st.write(f"• {symbol}")
                        if len(subscribed_symbols) > 10:
                            st.write(f"... and {len(subscribed_symbols) - 10} more")
    
    def _latency_indicator(self, latency_ms: float):
        """延迟状态指示器"""
        if latency_ms < 50:
            color = "🟢"
            status = "Excellent"
        elif latency_ms < 100:
            color = "🟡"
            status = "Good"
        elif latency_ms < 500:
            color = "🟠"
            status = "Fair"
        else:
            color = "🔴"
            status = "Poor"
        
        st.progress(
            min(latency_ms / 1000, 1.0),
            text=f"{color} {status} ({latency_ms:.1f}ms)"
        )
    
    def _create_latency_charts_tab(self, selected_adapters: list, history_length: int):
        """创建延迟图表标签页"""
        
        # 延迟趋势图表
        st.subheader("Latency Trends")
        
        fig = go.Figure()
        
        for adapter_name in selected_adapters:
            if adapter_name in self.history:
                history = self.history[adapter_name]
                if history['timestamps'] and history['avg_latency_ms']:
                    # 转换为相对时间（分钟）
                    base_time = history['timestamps'][0] if history['timestamps'] else 0
                    rel_times = [(t - base_time) / 60 for t in history['timestamps'][-history_length:]]
                    latencies = history['avg_latency_ms'][-history_length:]
                    
                    fig.add_trace(go.Scatter(
                        x=rel_times,
                        y=latencies,
                        mode='lines+markers',
                        name=adapter_name,
                        line=dict(width=2)
                    ))
        
        fig.update_layout(
            title="Average Latency Over Time",
            xaxis_title="Time (minutes)",
            yaxis_title="Latency (ms)",
            hovermode='x unified',
            height=400
        )
        
        st.plotly_chart(fig, use_container_width=True)
        
        # 成功率趋势图表
        st.subheader("Success Rate Trends")
        
        fig2 = go.Figure()
        
        for adapter_name in selected_adapters:
            if adapter_name in self.history:
                history = self.history[adapter_name]
                if history['timestamps'] and history['success_rate']:
                    base_time = history['timestamps'][0] if history['timestamps'] else 0
                    rel_times = [(t - base_time) / 60 for t in history['timestamps'][-history_length:]]
                    success_rates = [rate * 100 for rate in history['success_rate'][-history_length:]]
                    
                    fig2.add_trace(go.Scatter(
                        x=rel_times,
                        y=success_rates,
                        mode='lines+markers',
                        name=adapter_name,
                        line=dict(width=2)
                    ))
        
        fig2.update_layout(
            title="Success Rate Over Time",
            xaxis_title="Time (minutes)",
            yaxis_title="Success Rate (%)",
            hovermode='x unified',
            height=400,
            yaxis_range=[0, 100]
        )
        
        st.plotly_chart(fig2, use_container_width=True)
    
    def _create_detailed_metrics_tab(self, summary: Dict, selected_adapters: list):
        """创建详细指标标签页"""
        
        for adapter_name in selected_adapters:
            metrics = summary.get(adapter_name, {})
            
            with st.expander(f"{adapter_name.upper()} - Detailed Metrics", expanded=False):
                col1, col2 = st.columns(2)
                
                with col1:
                    st.markdown("#### 📊 Performance Metrics")
                    
                    st.metric("Total Messages", metrics.get('messages_received', 0))
                    st.metric("Messages Processed", metrics.get('messages_processed', 0))
                    st.metric("Errors", metrics.get('errors', 0))
                    st.metric("Error Rate", f"{metrics.get('error_rate', 0)*100:.2f}%")
                    st.metric("Connection Errors", metrics.get('connection_errors', 0))
                    
                    # Binance特有指标
                    if metrics.get('adapter_type') == 'binance':
                        st.markdown("#### 🔍 Binance Specific")
                        st.metric("Validations Total", metrics.get('validations_total', 0))
                        st.metric("Validation Success Rate", f"{metrics.get('validation_success_rate', 0)*100:.1f}%")
                        st.metric("Avg Pending Buffer", f"{metrics.get('avg_pending_buffer', 0):.1f}")
                
                with col2:
                    st.markdown("#### ⏱️ Latency Metrics")
                    
                    st.metric("Min Latency", f"{metrics.get('latency_min', 0):.1f}ms")
                    st.metric("Avg Latency", f"{metrics.get('avg_latency_ms', 0):.1f}ms")
                    st.metric("P50 Latency", f"{metrics.get('p50_latency_ms', 0):.1f}ms")
                    st.metric("P95 Latency", f"{metrics.get('p95_latency_ms', 0):.1f}ms")
                    st.metric("P99 Latency", f"{metrics.get('p99_latency_ms', 0):.1f}ms")
                    st.metric("Max Latency", f"{metrics.get('max_latency_ms', 0):.1f}ms")
    
    def _create_control_tab(self):
        """创建控制标签页"""
        st.subheader("Monitor Control")
        
        col1, col2 = st.columns(2)
        
        with col1:
            # 发送测试命令
            if st.button("📊 Get Current Summary", use_container_width=True):
                # 这里可以扩展为通过WebSocket发送命令
                st.info("Feature coming soon: Send command via WebSocket")
        
        with col2:
            # 清除历史数据
            if st.button("🗑️ Clear History", use_container_width=True):
                self.history.clear()
                st.success("History data cleared")
        
        # 实时数据流信息
        st.subheader("Real-time Data Stream")
        
        # 显示数据流统计
        data_stream_info = {
            "WebSocket Status": self.connection_status,
            "Last Update": datetime.now().strftime("%H:%M:%S"),
            "Connected Adapters": len(self.current_summary),
            "History Points": sum(len(h['timestamps']) for h in self.history.values())
        }
        
        for key, value in data_stream_info.items():
            st.write(f"**{key}:** {value}")

    def _test_connection(self):
        """测试WebSocket连接"""
        import websockets
        try:
            logger.info(f"测试连接到: {self.websocket_uri}")
            # 尝试直接连接
            async def test():
                try:
                    ws = await websockets.connect(self.websocket_uri, timeout=5)
                    await ws.close()
                    return True
                except Exception as e:
                    logger.error(f"测试连接失败: {e}")
                    return False
            
            # 在线程中运行异步测试
            import threading
            result = [False]
            def run_test():
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                result[0] = loop.run_until_complete(test())
                loop.close()
            
            thread = threading.Thread(target=run_test)
            thread.start()
            thread.join(timeout=10)
            
            return result[0]
        except Exception as e:
            logger.error(f"测试连接异常: {e}")
            return False        


# 使用示例
if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='启动WebSocket监控仪表板')
    parser.add_argument('--ws-uri', default='ws://localhost:9999/ws',
                       help='WebSocket服务器地址')
    
    args = parser.parse_args()
    
    # 创建仪表板
    dashboard = MonitorDashboard(websocket_uri=args.ws_uri)
    
    # 启动仪表板
    dashboard.create_dashboard()