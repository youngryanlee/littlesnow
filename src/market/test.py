import pytest
import asyncio
import logging
import sys
import os

# 添加 src 目录到 Python 路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from market import (
    BinanceAdapter, BybitAdapter, 
    WebSocketManager, MarketRouter,
    MarketData, ExchangeType
)

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class TestMarketSystem:
    """市场系统测试类"""
    
    def test_adapter_creation(self):
        """测试适配器创建"""
        binance = BinanceAdapter()
        bybit = BybitAdapter()
        
        assert binance.name == "binance"
        assert bybit.name == "bybit"
        assert binance.exchange_type == ExchangeType.BINANCE
        assert bybit.exchange_type == ExchangeType.BYBIT
    
    def test_manager_registration(self):
        """测试管理器注册"""
        ws_manager = WebSocketManager()
        binance = BinanceAdapter()
        bybit = BybitAdapter()
        
        ws_manager.register_adapter('binance', binance)
        ws_manager.register_adapter('bybit', bybit)
        
        assert 'binance' in ws_manager.adapters
        assert 'bybit' in ws_manager.adapters
        assert ws_manager.adapters['binance'] == binance
        assert ws_manager.adapters['bybit'] == bybit
    
    def test_router_registration(self):
        """测试路由器注册"""
        market_router = MarketRouter()
        binance = BinanceAdapter()
        
        market_router.register_adapter('binance', binance)
        
        # 这里可以添加更多路由器测试
    
    @pytest.mark.asyncio
    async def test_adapter_connection(self):
        """测试适配器连接（异步）"""
        binance = BinanceAdapter()
        
        # 测试连接方法存在
        assert hasattr(binance, 'connect')
        assert hasattr(binance, 'disconnect')
        
        # 注意：这里不实际连接，只是测试接口
        # 实际连接测试应该在集成测试中

if __name__ == "__main__":
    # 可以直接运行这个文件进行测试
    pytest.main([__file__, "-v"])