# src/market/service/proxy_manager.py
import os
import subprocess
from typing import Optional

from logger.logger import get_logger

logger = get_logger()

class ProxyManager:
    """通用的代理管理器"""
    
    @staticmethod
    def detect_proxy() -> Optional[str]:
        """自动检测代理设置 - 与 WebSocketConnector 相同的逻辑"""
        # 1. 首先检查环境变量
        env_proxy = (os.getenv('BINANCE_PROXY') or 
                    os.getenv('HTTPS_PROXY') or 
                    os.getenv('HTTP_PROXY') or
                    os.getenv('ALL_PROXY'))
        
        if env_proxy:
            logger.info(f"使用环境变量代理: {env_proxy}")
            return env_proxy
        
        # 2. 尝试检测 macOS 系统代理
        try:
            system_proxy = ProxyManager._get_macos_system_proxy()
            if system_proxy:
                logger.debug(f"检测到系统代理: {system_proxy}")
                return system_proxy
        except Exception as e:
            logger.exception(f"系统代理检测失败: {e}")
        
        logger.debug("未检测到代理配置")
        return None
    
    @staticmethod
    def _get_macos_system_proxy() -> Optional[str]:
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
                        logger.debug(f"在服务 {service} 中找到系统代理: {proxy_url}")
                        return proxy_url
            
            return None
            
        except Exception as e:
            logger.debug(f"macOS 系统代理检测异常: {e}")
            return None