# src/market/monitor/service.py
"""
监控服务 - 包含WebSocket服务器自动启动
"""
import asyncio
import subprocess
import threading
import time
import logging
import signal
import os
import sys
from typing import Dict, Any, Optional, List
from datetime import datetime
import webbrowser

from logger.logger import get_logger

logger = get_logger()

class MonitorService:
    """监控服务 - 只负责显示，不负责数据收集"""
    
    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 8000,
        auto_start_websocket: bool = True,
        open_browser: bool = True
    ):
        """
        Args:
            host: WebSocket服务器主机地址
            port: WebSocket服务器端口
            auto_start_websocket: 是否自动启动WebSocket服务器
            open_browser: 是否自动打开浏览器
        """
        self.host = host
        self.port = port
        self.auto_start_websocket = auto_start_websocket
        self.open_browser = open_browser
        
        # 配置
        self.update_interval = 1.0
        self.max_history = 1000
        
        # 外部传入的监控器引用
        self.monitor = None
        
        # WebSocket服务器进程
        self.websocket_process = None
        self.websocket_url = f"http://{host}:{port}"
        
        # 运行状态
        self.is_running = False
        self.metrics_history = []
    
    def set_monitor(self, monitor):
        """设置外部监控器（从测试脚本传入）"""
        self.monitor = monitor
        logger.info(f"✅ 已设置外部监控器: {monitor}")
    
    def _start_websocket_server(self):
        """启动WebSocket服务器子进程"""
        try:
            # 构建app.py的路径
            import market.monitor.backend.app as app_module
            app_file = app_module.__file__

            env = os.environ.copy()

            # 项目结构是：
            # littlesnow/
            #   src/
            #     market/
            project_root = os.path.abspath(
                os.path.join(os.path.dirname(__file__), "..", "..", "..")
            )
            src_path = os.path.join(project_root, "src")

            env["PYTHONPATH"] = src_path + (
                ":" + env["PYTHONPATH"] if "PYTHONPATH" in env else ""
            )
            
            logger.info(f"🚀 启动WebSocket服务器: {self.host}:{self.port}")
            
            # 使用uvicorn启动app.py
            cmd = [
                sys.executable,  # 使用当前Python解释器
                "-m", "uvicorn",
                "market.monitor.backend.app:app",
                "--host", self.host,
                "--port", str(self.port),
                "--log-level", "info"
            ]
            
            # 启动子进程
            self.websocket_process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                universal_newlines=True,
                bufsize=1,
                env=env,
                cwd=project_root
            )
            
            # 启动输出读取线程
            def read_output():
                while True:
                    output = self.websocket_process.stdout.readline()
                    if output:
                        logger.debug(f"[WebSocket Server] {output.strip()}")
                    if self.websocket_process.poll() is not None:
                        break
            
            thread = threading.Thread(target=read_output, daemon=True)
            thread.start()
            
            # 等待服务器启动
            time.sleep(3)
            
            # 检查服务器是否启动成功
            import requests
            try:
                response = requests.get(f"{self.websocket_url}/api/health", timeout=5)
                if response.status_code == 200:
                    logger.info("✅ WebSocket服务器启动成功")
                    
                    # 自动打开浏览器
                    if self.open_browser:
                        webbrowser.open(self.websocket_url)
                        logger.info(f"🌐 已打开浏览器: {self.websocket_url}")
                    
                    return True
                else:
                    logger.error(f"❌ WebSocket服务器启动失败: HTTP {response.status_code}")
                    return False
            except Exception as e:
                logger.error(f"❌ WebSocket服务器启动失败: {e}")
                return False
            
        except Exception as e:
            logger.error(f"❌ 启动WebSocket服务器失败: {e}", exc_info=True)
            return False
    
    def _stop_websocket_server(self):
        """停止WebSocket服务器子进程"""
        if self.websocket_process:
            logger.info("停止WebSocket服务器...")
            
            # 发送SIGTERM信号
            self.websocket_process.terminate()
            
            try:
                # 等待5秒
                self.websocket_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                # 如果超时，强制终止
                self.websocket_process.kill()
                self.websocket_process.wait()
            
            logger.info("✅ WebSocket服务器已停止")
            self.websocket_process = None
    
    async def start_monitoring(self, duration_hours: Optional[float] = None):
        """启动监控服务（只负责显示，不负责数据收集）"""
        if self.is_running:
            logger.warning("监控服务已在运行中")
            return False
        
        try:
            # 自动启动WebSocket服务器
            if self.auto_start_websocket:
                if not self._start_websocket_server():
                    logger.warning("⚠️ WebSocket服务器启动失败，继续启动监控服务...")
            
            # 检查是否有外部监控器
            if not self.monitor:
                logger.warning("⚠️ 没有设置外部监控器，前端将无法显示数据")
            
            self.is_running = True
            
            # 发送启动通知到WebSocket服务器
            await self._send_start_notification(duration_hours)
            
            # 启动数据推送循环
            asyncio.create_task(self._monitoring_loop(duration_hours))
            
            logger.info(f"✅ 监控显示服务已启动")
            if self.auto_start_websocket:
                logger.info(f"🌐 前端访问: {self.websocket_url}")
            
            return True
            
        except Exception as e:
            logger.error(f"❌ 启动监控服务失败: {e}", exc_info=True)
            self.is_running = False
            return False
    
    async def _send_start_notification(self, duration_hours: Optional[float] = None):
        """发送启动通知到WebSocket服务器"""
        try:
            import aiohttp
            
            async with aiohttp.ClientSession() as session:
                data = {
                    "type": "status",
                    "is_monitoring": True,
                    "duration_hours": duration_hours,
                    "message": f"监控已启动，时长: {duration_hours}小时" if duration_hours else "监控已启动",
                    "timestamp": datetime.now().isoformat()
                }
                
                async with session.post(
                    f"{self.websocket_url}/api/push/status",
                    json=data,
                    timeout=5
                ) as response:
                    if response.status == 200:
                        logger.debug("启动通知发送成功")
                    else:
                        logger.warning(f"启动通知发送失败: HTTP {response.status}")
        except Exception as e:
            logger.warning(f"无法发送启动通知: {e}")
    
    async def _monitoring_loop(self, duration_hours: Optional[float] = None):
        """监控循环 - 只推送数据，不收集数据"""
        start_time = time.time()
        
        while self.is_running:
            try:
                # 检查是否超时
                if duration_hours:
                    elapsed = (time.time() - start_time) / 3600
                    if elapsed >= duration_hours:
                        logger.info(f"⏰ 监控时长已达到 {duration_hours} 小时，停止监控")
                        await self.stop_monitoring()
                        break
                
                # 从外部监控器获取指标
                metrics = self._get_current_metrics()
                print("========>>>>>>>>metrics:", metrics)
                
                # 保存历史
                if metrics:
                    self.metrics_history.append({
                        'timestamp': datetime.now().isoformat(),
                        'metrics': metrics
                    })
                    
                    # 限制历史记录长度
                    if len(self.metrics_history) > self.max_history:
                        self.metrics_history.pop(0)
                
                # 推送数据到WebSocket服务器
                await self._push_metrics_to_server(metrics, elapsed if duration_hours else None)
                
                # 等待下一次推送
                await asyncio.sleep(self.update_interval)
                
            except Exception as e:
                logger.error(f"监控循环出错: {e}")
                await asyncio.sleep(5)
    
    def _get_current_metrics(self) -> Dict[str, Any]:
        """从外部监控器获取当前指标"""
        if not self.monitor:
            return {}
        
        try:
            return self.monitor.get_summary()
        except Exception as e:
            logger.error(f"获取外部监控器指标失败: {e}")
            return {}
    
    async def _push_metrics_to_server(self, metrics: Dict[str, Any], elapsed_hours: Optional[float] = None):
        """推送指标数据到WebSocket服务器"""
        if not self.auto_start_websocket:
            return
        
        try:
            import aiohttp
            
            data = {
                "type": "metrics_update",
                "timestamp": datetime.now().isoformat(),
                "data": {
                    "summary": metrics,
                    "test_info": {
                        "status": "running",
                        "is_monitoring": True,
                        "elapsed_hours": elapsed_hours,
                        "duration_hours": elapsed_hours  # 对于无限时长的监控，显示已运行时长
                    }
                }
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.websocket_url}/api/push/metrics",
                    json=data,
                    timeout=5
                ) as response:
                    if response.status != 200:
                        logger.warning(f"推送指标数据失败: HTTP {response.status}")
                        
        except Exception as e:
            logger.warning(f"推送指标数据失败: {e}")
    
    async def stop_monitoring(self):
        """停止监控服务"""
        if not self.is_running:
            return
        
        self.is_running = False
        
        # 发送停止通知到WebSocket服务器
        await self._send_stop_notification()
        
        # 停止WebSocket服务器（如果自动启动的）
        if self.auto_start_websocket:
            self._stop_websocket_server()
        
        logger.info("✅ 监控服务已停止")
    
    async def _send_stop_notification(self):
        """发送停止通知到WebSocket服务器"""
        try:
            import aiohttp
            
            async with aiohttp.ClientSession() as session:
                data = {
                    "type": "test_complete",
                    "message": "监控已停止",
                    "timestamp": datetime.now().isoformat()
                }
                
                async with session.post(
                    f"{self.websocket_url}/api/push/test_complete",
                    json=data,
                    timeout=5
                ) as response:
                    if response.status == 200:
                        logger.debug("停止通知发送成功")
                    else:
                        logger.warning(f"停止通知发送失败: HTTP {response.status}")
        except Exception as e:
            logger.warning(f"无法发送停止通知: {e}")
    
    def __del__(self):
        """析构函数 - 确保清理资源"""
        if self.websocket_process:
            self._stop_websocket_server()