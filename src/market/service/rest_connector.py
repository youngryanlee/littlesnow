# src/market/service/rest_connector.py
import aiohttp
import asyncio
import logging
from typing import Optional, Dict, Any
from .proxy_manager import ProxyManager

logger = logging.getLogger(__name__)

class RESTConnector:
    """通用的 REST API 连接器 - 内部自动处理代理配置"""
    
    def __init__(self, 
                 base_url: str = "",
                 timeout: int = 15,
                 name: str = "rest_connector",
                 proxy: Optional[str] = None):
        
        self.base_url = base_url
        self.timeout = aiohttp.ClientTimeout(total=timeout)
        self.name = name
        
        # 代理配置优先级：手动传入 > 环境变量 > 系统代理检测
        self.proxy = proxy or ProxyManager.detect_proxy()
        
        self.session: Optional[aiohttp.ClientSession] = None
    
    async def __aenter__(self):
        await self.connect()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.disconnect()
    
    async def connect(self):
        """创建会话"""
        if self.session is None:
            connector_kwargs = {}
            if self.proxy and self.proxy.startswith(('http://', 'https://')):
                connector_kwargs['proxy'] = self.proxy
                logger.info(f"[{self.name}] 使用代理: {self.proxy}")
            
            self.session = aiohttp.ClientSession(
                timeout=self.timeout,
                **connector_kwargs
            )
    
    async def disconnect(self):
        """关闭会话"""
        if self.session:
            await self.session.close()
            self.session = None
    
    async def get(self, url: str, **kwargs) -> aiohttp.ClientResponse:
        """发送 GET 请求"""
        if not self.session:
            await self.connect()
        
        # 如果 URL 不是完整路径，添加 base_url
        if not url.startswith(('http://', 'https://')) and self.base_url:
            url = self.base_url + url
        
        logger.debug(f"[{self.name}] GET {url}")
        return await self.session.get(url, **kwargs)
    
    async def post(self, url: str, **kwargs) -> aiohttp.ClientResponse:
        """发送 POST 请求"""
        if not self.session:
            await self.connect()
        
        if not url.startswith(('http://', 'https://')) and self.base_url:
            url = self.base_url + url
        
        logger.debug(f"[{self.name}] POST {url}")
        return await self.session.post(url, **kwargs)
    
    async def get_json(self, url: str, **kwargs) -> Dict[str, Any]:
        """发送 GET 请求并返回 JSON 数据"""
        async with await self.get(url, **kwargs) as response:
            if response.status == 200:
                return await response.json()
            else:
                error_text = await response.text()
                raise aiohttp.ClientError(f"HTTP {response.status}: {error_text}")