使用示例
方式1：传统方式（保持兼容）
python
# 任何文件中
from utils.logger import logger

logger.info("使用默认logger")  # 输出: PolymarketBot - INFO - 使用默认logger
方式2：模块特定logger（推荐）
python
# market/adapters/binance_adapter.py
from utils.logger import get_module_logger

logger = get_module_logger()  # 自动使用 "market.adapters.binance_adapter"

class BinanceAdapter:
    def connect(self):
        logger.info("连接币安...")  # 输出: market.adapters.binance_adapter - INFO - 连接币安...
方式3：显式指定名称
python
# market/services/ws_manager.py
from utils.logger import LoggerFactory

logger = LoggerFactory.get_logger("websocket.manager")

class WebSocketManager:
    def start(self):
        logger.info("启动WebSocket管理器")  # 输出: websocket.manager - INFO - 启动WebSocket管理器
方式4：在测试中使用
python
# test/test_binance.py
from utils.logger import get_module_logger
import logging

logger = get_module_logger(logging.DEBUG)  # 测试时使用DEBUG级别

def test_connection():
    logger.debug("详细调试信息")  # 控制台可能不显示，但会记录到文件
    logger.info("测试开始")
高级功能
动态调整日志级别
python
from utils.logger import LoggerFactory
import logging

# 为特定模块设置不同级别
adapter_logger = LoggerFactory.get_logger("market.adapters")
adapter_logger.setLevel(logging.DEBUG)

service_logger = LoggerFactory.get_logger("market.services") 
service_logger.setLevel(logging.WARNING)
在配置文件中使用
python
# config/logging_config.py
import logging
from utils.logger import LoggerFactory

# 根据环境配置日志级别
def setup_logging_config(environment="production"):
    if environment == "development":
        level = logging.DEBUG
    else:
        level = logging.INFO
    
    # 配置根logger
    root_logger = LoggerFactory.get_logger()
    for handler in root_logger.handlers:
        if isinstance(handler, logging.StreamHandler):
            handler.setLevel(level)
