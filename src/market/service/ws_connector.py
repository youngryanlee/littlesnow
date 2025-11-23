import aiohttp
import asyncio
import logging
import json
import os
import subprocess
import re
from typing import Callable, Optional, Dict, Any
from aiohttp import ClientSession, ClientWSTimeout, client_exceptions

logger = logging.getLogger(__name__)

class WebSocketConnector:
    """通用的 WebSocket 连接器 - 内部自动处理代理配置"""
    
    def __init__(self, 
                 url: str, 
                 on_message: Callable[[Dict[str, Any]], None],
                 on_error: Callable[[Exception], None] = None,
                 ping_interval: int = 30,
                 timeout: int = 10,
                 name: str = "unknown",
                 proxy: Optional[str] = None):  # 可选的手动代理配置
        
        self.url = url
        self.on_message = on_message
        self.on_error = on_error
        self.ping_interval = ping_interval
        self.timeout = timeout
        self.name = name
        
        # 代理配置优先级：手动传入 > 环境变量 > 系统代理检测
        self.proxy = proxy or self._detect_proxy()
        
        self.session: Optional[aiohttp.ClientSession] = None
        self.ws: Optional[aiohttp.ClientSessionWsConnection] = None
        self.is_connected = False
        self._message_task: Optional[asyncio.Task] = None
    
    def _detect_proxy(self) -> Optional[str]:
        """自动检测代理设置"""
        # 1. 首先检查环境变量
        env_proxy = (os.getenv('BINANCE_PROXY') or 
                    os.getenv('HTTPS_PROXY') or 
                    os.getenv('HTTP_PROXY') or
                    os.getenv('ALL_PROXY'))
        
        if env_proxy:
            logger.info(f"[{self.name}] 使用环境变量代理: {env_proxy}")
            return env_proxy
        
        # 2. 尝试检测 macOS 系统代理
        try:
            system_proxy = self._get_macos_system_proxy()
            if system_proxy:
                logger.info(f"[{self.name}] 检测到系统代理: {system_proxy}")
                return system_proxy
        except Exception as e:
            logger.debug(f"[{self.name}] 系统代理检测失败: {e}")
        
        logger.debug(f"[{self.name}] 未检测到代理配置")
        return None
    
    def _get_macos_system_proxy(self) -> Optional[str]:
        """获取 macOS 系统代理设置"""
        try:
            # 获取当前网络服务（通常是 Wi-Fi 或 Ethernet）
            services_result = subprocess.run(
                ['networksetup', '-listallnetworkservices'],
                capture_output=True, text=True, timeout=5
            )
            
            if services_result.returncode != 0:
                return None
                
            services = [line.strip() for line in services_result.stdout.split('\n') 
                       if line.strip() and not line.startswith('*')]
            
            # 检查每个服务的代理设置
            for service in services:
                # 检查 Web 代理 (HTTP)
                http_proxy_result = subprocess.run(
                    ['networksetup', '-getwebproxy', service],
                    capture_output=True, text=True, timeout=5
                )
                
                if http_proxy_result.returncode == 0 and 'Enabled: Yes' in http_proxy_result.stdout:
                    # 解析代理服务器和端口
                    server_line = [line for line in http_proxy_result.stdout.split('\n') 
                                 if 'Server:' in line][0]
                    port_line = [line for line in http_proxy_result.stdout.split('\n') 
                               if 'Port:' in line][0]
                    
                    server = server_line.split(':', 1)[1].strip()
                    port = port_line.split(':', 1)[1].strip()
                    
                    if server and port:
                        proxy_url = f"http://{server}:{port}"
                        logger.debug(f"[{self.name}] 在服务 {service} 中找到系统代理: {proxy_url}")
                        return proxy_url
            
            return None
            
        except Exception as e:
            logger.debug(f"[{self.name}] macOS 系统代理检测异常: {e}")
            return None
        
    async def connect(self) -> bool:
        """建立 WebSocket 连接"""
        try:
            self.session = aiohttp.ClientSession()
            
            # 准备连接参数
            connect_kwargs = {
                'heartbeat': self.ping_interval,
                'timeout': ClientWSTimeout(ws_close=self.timeout),
                'autoclose': True,
                'autoping': True
            }
            
            # 如果有代理配置，添加到连接参数中
            if self.proxy:
                connect_kwargs['proxy'] = self.proxy
                logger.info(f"[{self.name}] 使用代理连接: {self.proxy}")
            
            self.ws = await self.session.ws_connect(
                self.url,
                **connect_kwargs
            )
            self.is_connected = True
            
            # 启动消息处理循环
            self._message_task = asyncio.create_task(self._message_loop())
            logger.info(f"[{self.name}] WebSocket connected to {self.url}")
            return True
            
        except Exception as e:
            logger.error(f"[{self.name}] WebSocket connection failed: {e}")
            if self.on_error:
                self.on_error(e)
            return False
            
    async def disconnect(self):
        """断开 WebSocket 连接"""
        self.is_connected = False
        
        # 取消消息处理任务
        if self._message_task and not self._message_task.done():
            self._message_task.cancel()
            try:
                await self._message_task
            except asyncio.CancelledError:
                pass
                
        # 关闭 WebSocket 连接
        if self.ws:
            await self.ws.close()
            
        # 关闭会话
        if self.session:
            await self.session.close()
            
        logger.info(f"[{self.name}] WebSocket disconnected")
        
    async def send_json(self, data: Dict[str, Any]):
        """发送 JSON 数据"""
        if self.ws and not self.ws.closed:
            await self.ws.send_json(data)
            logger.debug(f"[{self.name}] Sent JSON message: {data}")
        else:
            logger.warning(f"[{self.name}] Cannot send message, WebSocket is not connected")
            
    async def send_text(self, text: str):
        """发送文本数据"""
        if self.ws and not self.ws.closed:
            await self.ws.send_str(text)
            logger.debug(f"[{self.name}] Sent text message: {text}")
        else:
            logger.warning(f"[{self.name}] Cannot send message, WebSocket is not connected")
            
    async def _message_loop(self):
        """消息处理循环"""
        try:
            async for msg in self.ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    try:
                        data = json.loads(msg.data)
                        logger.debug(f"[{self.name}] Received message: {data}")
                        self.on_message(data)
                    except json.JSONDecodeError as e:
                        logger.error(f"[{self.name}] Failed to parse JSON message: {e}")
                    except Exception as e:
                        logger.error(f"[{self.name}] Error processing message: {e}")
                        
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    logger.error(f"[{self.name}] WebSocket error occurred")
                    self.is_connected = False
                    if self.on_error:
                        self.on_error(Exception("WebSocket error"))
                    break
                    
                elif msg.type == aiohttp.WSMsgType.CLOSED:
                    logger.info(f"[{self.name}] WebSocket connection closed")
                    self.is_connected = False
                    break
                    
                elif msg.type == aiohttp.WSMsgType.CLOSE:
                    logger.info(f"[{self.name}] WebSocket close message received")
                    self.is_connected = False
                    break
                    
        except asyncio.CancelledError:
            logger.debug(f"[{self.name}] Message loop cancelled")
        except Exception as e:
            logger.error(f"[{self.name}] Message loop error: {e}")
            self.is_connected = False
            if self.on_error:
                self.on_error(e)
                
    def get_connection_info(self) -> Dict[str, Any]:
        """获取连接信息"""
        return {
            "name": self.name,
            "url": self.url,
            "is_connected": self.is_connected,
            "ping_interval": self.ping_interval,
            "timeout": self.timeout,
            "proxy": self.proxy  # 包含代理信息用于调试
        }