import asyncio
import logging
from typing import Dict, List
import time

from ..adapter.base import BaseAdapter
from ..core.base_adapter import BaseMarketAdapter

logger = logging.getLogger(__name__)

class WebSocketManager:
    """WebSocket 连接管理器 - 修复版本"""
    
    def __init__(self):
        self.adapters: Dict[str, BaseMarketAdapter] = {}
        self.is_running = False
        self.reconnect_attempts: Dict[str, int] = {}
        self.max_reconnect_attempts = 5
        
    def register_adapter(self, name: str, adapter: BaseMarketAdapter):
        """注册适配器"""
        self.adapters[name] = adapter
        self.reconnect_attempts[name] = 0
        logger.info(f"Registered adapter: {name}")
        
    async def start(self):
        """启动所有 WebSocket 连接"""
        self.is_running = True
        tasks = []
        
        for name, adapter in self.adapters.items():
            task = asyncio.create_task(self._manage_adapter_connection(name, adapter))
            tasks.append(task)
            
        # 不要等待管理任务完成，让它们后台运行
        asyncio.create_task(self._monitor_tasks(tasks))
        
    async def _monitor_tasks(self, tasks: List[asyncio.Task]):
        """监控任务状态"""
        try:
            await asyncio.gather(*tasks)
        except Exception as e:
            logger.error(f"Error in connection management tasks: {e}")
        
    async def stop(self):
        """停止所有 WebSocket 连接"""
        self.is_running = False
        disconnect_tasks = []
        for adapter in self.adapters.values():
            if hasattr(adapter, 'disconnect'):
                disconnect_tasks.append(adapter.disconnect())
            
        if disconnect_tasks:
            await asyncio.gather(*disconnect_tasks, return_exceptions=True)
        logger.info("All WebSocket connections stopped")
        
    async def _manage_adapter_connection(self, name: str, adapter: BaseMarketAdapter):
        """管理适配器连接 - 修复版本"""
        logger.info(f"Starting connection management for {name}")
        
        while self.is_running:
            try:
                if not adapter.is_connected:
                    logger.info(f"Connecting {name}...")
                    success = await adapter.connect()
                    
                    if success:
                        logger.info(f"{name} connected successfully")
                        self.reconnect_attempts[name] = 0
                        
                        # 连接成功后重新订阅之前的交易对
                        if hasattr(adapter, 'subscribed_symbols') and adapter.subscribed_symbols:
                            symbols = list(adapter.subscribed_symbols)
                            logger.info(f"Resubscribing to {symbols} on {name}")
                            await adapter.subscribe(symbols)
                    else:
                        self.reconnect_attempts[name] += 1
                        wait_time = min(2 ** self.reconnect_attempts[name], 60)
                        logger.warning(f"{name} connection failed, attempt {self.reconnect_attempts[name]}, waiting {wait_time}s")
                        await asyncio.sleep(wait_time)
                        continue
                else:
                    # 连接已建立，进行健康检查
                    if await self._health_check(adapter):
                        logger.info(f"{name} health check passed")
                    else:
                        logger.warning(f"{name} health check failed, reconnecting...")
                        await adapter.disconnect()
                        continue
                        
                # 短暂的等待，避免过于频繁的检查
                await asyncio.sleep(2)
                
            except asyncio.CancelledError:
                logger.debug(f"Connection management for {name} cancelled")
                break
            except Exception as e:
                logger.error(f"Error managing {name} connection: {e}")
                self.reconnect_attempts[name] += 1
                wait_time = min(2 ** self.reconnect_attempts[name], 60)
                await asyncio.sleep(wait_time)
                
        logger.info(f"Connection management for {name} stopped")
                
    async def _health_check(self, adapter: BaseMarketAdapter) -> bool:
        """简单的健康检查"""
        # 这里可以实现更复杂的健康检查逻辑
        # 目前只是检查连接状态
        return adapter.is_connected
                
    def get_connection_status(self) -> Dict[str, bool]:
        """获取所有适配器的连接状态"""
        return {name: adapter.is_connected for name, adapter in self.adapters.items()}
        
    def get_detailed_status(self) -> Dict[str, Dict]:
        """获取详细的连接状态信息"""
        status = {}
        for name, adapter in self.adapters.items():
            if hasattr(adapter, 'get_connection_status'):
                status[name] = adapter.get_connection_status()
            else:
                status[name] = {
                    'is_connected': adapter.is_connected,
                    'name': name
                }
        return status
        
    async def subscribe_all(self, symbols: List[str]):
        """在所有适配器上订阅交易对"""
        subscription_tasks = []
        for name, adapter in self.adapters.items():
            if adapter.is_connected:
                logger.info(f"Subscribing {name} to {symbols}")
                subscription_tasks.append(adapter.subscribe(symbols))
        
        if subscription_tasks:
            await asyncio.gather(*subscription_tasks, return_exceptions=True)
            logger.info(f"Subscribed all adapters to {symbols}")