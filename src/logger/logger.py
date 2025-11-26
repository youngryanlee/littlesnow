# utils/logger.py
import logging
import sys
import os
from datetime import datetime
from typing import Optional
from colorama import Fore, Style, init

# 初始化colorama
init()

# 创建logs目录
os.makedirs('logs', exist_ok=True)

class ColoredFormatter(logging.Formatter):
    """带颜色的日志格式化器"""
    
    COLORS = {
        'DEBUG': Fore.CYAN,
        'INFO': Fore.GREEN,
        'WARNING': Fore.YELLOW,
        'ERROR': Fore.RED,
        'CRITICAL': Fore.RED + Style.BRIGHT
    }
    
    def format(self, record):
        log_color = self.COLORS.get(record.levelname, '')
        message = super().format(record)
        return f"{log_color}{message}{Style.RESET_ALL}"

class LoggerFactory:
    """Logger工厂类，管理所有logger实例"""
    
    _configured_loggers = set()
    
    @classmethod
    def get_logger(cls, name: Optional[str] = None, level: int = logging.INFO) -> logging.Logger:
        """
        获取或创建logger
        
        Args:
            name: logger名称，如果为None则使用调用者的模块名
            level: 日志级别
        
        Returns:
            配置好的logger实例
        """
        if name is None:
            # 自动获取调用者的模块名
            import inspect
            frame = inspect.currentframe().f_back
            module = inspect.getmodule(frame)
            name = module.__name__ if module else "unknown"
        
        logger = logging.getLogger(name)
        
        # 如果这个logger还没有配置过，进行配置
        if name not in cls._configured_loggers:
            cls._setup_logger(logger, level)
            cls._configured_loggers.add(name)
        
        return logger
    
    @classmethod
    def _setup_logger(cls, logger: logging.Logger, level: int):
        """设置logger的处理器和格式"""
        logger.setLevel(logging.DEBUG)  # logger本身设置为最低级别
        
        # 避免重复添加handler（在某些情况下可能会重复）
        if logger.handlers:
            return
            
        # 1. 控制台Handler - 带颜色
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(level)
        console_formatter = ColoredFormatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        console_handler.setFormatter(console_formatter)
        
        # 2. 文件Handler - 不带颜色，记录更详细的信息
        log_filename = f"logs/polymarket_{datetime.now().strftime('%Y%m%d')}.log"
        file_handler = logging.FileHandler(log_filename, encoding='utf-8')
        file_handler.setLevel(logging.DEBUG)
        file_formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        file_handler.setFormatter(file_formatter)
        
        # 添加处理器
        logger.addHandler(console_handler)
        logger.addHandler(file_handler)
        
        # 防止日志传递给父logger（避免重复输出）
        logger.propagate = False

def setup_logger(name: Optional[str] = None, level: int = logging.INFO) -> logging.Logger:
    """
    设置并返回一个配置好的logger（兼容旧版本）
    
    Args:
        name: logger名称
        level: 日志级别
    
    Returns:
        配置好的logger实例
    """
    return LoggerFactory.get_logger(name, level)

# 便捷函数，用于快速获取模块logger
def get_logger(level: int = logging.INFO) -> logging.Logger:
    """
    快速获取当前模块的logger
    
    Returns:
        当前模块的logger实例
    """
    import inspect
    frame = inspect.currentframe().f_back
    module = inspect.getmodule(frame)
    name = module.__name__ if module else "unknown"
    return LoggerFactory.get_logger(name, level)

# 全局默认logger实例（保持向后兼容）
logger = setup_logger("PolymarketBot")