import aiohttp
import asyncio
import json
import os
import subprocess
import re
from typing import Callable, Optional, Dict, Any
from aiohttp import ClientSession, ClientWSTimeout, client_exceptions

from logger.logger import get_logger
from .proxy_manager import ProxyManager

logger = get_logger()

class WebSocketConnector:
    """通用的 WebSocket 连接器 - 内部自动处理代理配置"""
    
    def __init__(self, 
                 url: str, 
                 on_message: Callable[[Dict[str, Any]], None],
                 on_error: Callable[[Exception], None] = None,
                 ping_interval: int = 30,
                 timeout: int = 10,
                 name: str = "unknown",
                 proxy: Optional[str] = None):
        
        self.url = url
        self.on_message = on_message
        self.on_error = on_error
        self.ping_interval = ping_interval
        self.timeout = timeout
        self.name = name
        
        # 使用统一的代理管理器
        self.proxy = proxy or ProxyManager.detect_proxy()
        
        self.session: Optional[aiohttp.ClientSession] = None
        self.ws: Optional[aiohttp.ClientSessionWsConnection] = None
        self.is_connected = False
        self._message_task: Optional[asyncio.Task] = None
        
    async def connect(self) -> bool:
        """建立 WebSocket 连接"""
        try:
            self.session = aiohttp.ClientSession()
            logger.info(f"connect using session: {self.session}")
            
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
            self._message_task = None  # 清空引用
            
        # 关闭 WebSocket 连接
        if self.ws:
            await self.ws.close()
            self.ws = None  # 🎯 关键：清空引用
        
        # 关闭会话
        if self.session:
            logger.info(f"closing self.session: {self.session}")
            await self.session.close()
            self.session = None  # 🎯 关键：清空引用
        
        logger.info(f"[{self.name}] WebSocket disconnected")
        
    async def send_json(self, data: Dict[str, Any]):
        """发送 JSON 数据"""
        if self.ws and not self.ws.closed:
            await self.ws.send_json(data)
            logger.debug(f"[{self.name}] Sent JSON message: {data}: {self.ws}")
        else:
            logger.warning(f"[{self.name}] Cannot send message, WebSocket is not connected: {self.ws}")
            
    async def send_text(self, text: str):
        """发送文本数据"""
        if self.ws and not self.ws.closed:
            await self.ws.send_str(text)
            logger.debug(f"[{self.name}] Sent text message: {text}: {self.ws}")
        else:
            logger.warning(f"[{self.name}] Cannot send message: {text}, WebSocket is not connected: {self.ws}")
            
    async def _message_loop(self):
        """消息处理循环 - 健壮版本"""
        try:
            async for msg in self.ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    
                    # 处理各种类型的文本消息
                    await self._handle_text_message(msg)
                        
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

    async def _handle_text_message(self, msg):
        """处理文本消息"""
        try:
            # 处理特殊消息类型
            if msg.data in ['PONG', 'PING']:
                logger.debug(f"[{self.name}] Received heartbeat: {msg.data}")
                return
                
            # 检查是否是空消息
            if not msg.data or not msg.data.strip():
                logger.debug(f"[{self.name}] Received empty message")
                return
                
            # 安全解析 JSON
            data = self._safe_json_parse(msg.data)
            if data is not None:
                logger.debug(f"[{self.name}] Successfully parsed message")
                self.on_message(data)
            else:
                logger.warning(f"[{self.name}] Could not parse message: {msg.data[:100]}")
                
        except Exception as e:
            logger.error(f"[{self.name}] Error handling text message: {e}")

    def _safe_json_parse(self, message_str):
        """安全解析 JSON 消息"""
        try:
            return json.loads(message_str)
        except json.JSONDecodeError as e:
            logger.warning(f"[{self.name}] JSON decode failed: {e}")
            # 记录原始消息的前100个字符用于调试
            logger.debug(f"Problematic message: {message_str[:100]}")
            return None
                
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