import pytest
import asyncio
import logging
import sys
import os
from decimal import Decimal

# 添加 src 目录到 Python 路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from market import (
    BinanceAdapter, WebSocketManager, MarketRouter,
    MarketData, ExchangeType
)

# 配置详细日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

@pytest.mark.integration
@pytest.mark.asyncio
class TestBinanceLiveConnection:
    """币安真实连接测试"""
    
    async def test_binance_websocket_connection(self):
        """测试币安 WebSocket 真实连接和数据接收"""
        logger.info("开始币安真实连接测试...")
        
        # 创建适配器和管理器
        binance = BinanceAdapter()
        ws_manager = WebSocketManager()
        market_router = MarketRouter()
        
        # 注册适配器
        ws_manager.register_adapter('binance', binance)
        market_router.register_adapter('binance', binance)
        
        # 用于收集接收到的数据
        received_data = []
        
        def on_market_data(data: MarketData):
            """市场数据回调"""
            logger.info(f"收到市场数据: {data.symbol} - 交易所: {data.exchange.value}")
            if data.orderbook:
                logger.info(f"  订单簿: {len(data.orderbook.bids)} bids, {len(data.orderbook.asks)} asks")
            if data.last_price:
                logger.info(f"  最新价格: {data.last_price}")
            received_data.append(data)
        
        # 注册回调
        market_router.add_callback(on_market_data)
        
        try:
            # 启动 WebSocket 连接
            logger.info("启动 WebSocket 连接...")
            await ws_manager.start()
            
            # 等待连接建立
            logger.info("等待连接建立...")
            await asyncio.sleep(3)
            
            # 检查连接状态
            status = ws_manager.get_connection_status()
            logger.info(f"连接状态: {status}")
            
            assert status['binance'] == True, "币安连接应该成功"
            
            # 订阅交易对
            symbols = ['BTCUSDT', 'ETHUSDT']
            logger.info(f"订阅交易对: {symbols}")
            await ws_manager.subscribe_all(symbols)
            
            # 等待接收数据（30秒）
            logger.info("等待接收市场数据（30秒）...")
            start_time = asyncio.get_event_loop().time()
            while len(received_data) < 5 and (asyncio.get_event_loop().time() - start_time) < 30:
                await asyncio.sleep(1)
                logger.info(f"已收到 {len(received_data)} 条数据...")
            
            # 验证是否收到数据
            assert len(received_data) > 0, "应该至少收到一些市场数据"
            
            # 验证数据格式
            for data in received_data[:3]:  # 检查前3条数据
                assert isinstance(data, MarketData)
                assert data.symbol in symbols
                assert data.exchange == ExchangeType.BINANCE
                assert data.timestamp is not None
                logger.info(f"数据验证通过: {data.symbol}")
            
            logger.info(f"测试成功! 总共收到 {len(received_data)} 条市场数据")
            
        except Exception as e:
            logger.error(f"测试失败: {e}")
            raise
        finally:
            # 清理资源
            logger.info("清理资源...")
            await ws_manager.stop()
    
    async def test_binance_orderbook_data(self):
        """测试币安订单簿数据质量"""
        logger.info("测试币安订单簿数据质量...")
        
        binance = BinanceAdapter()
        market_router = MarketRouter()
        market_router.register_adapter('binance', binance)
        
        # 用于分析订单簿数据
        orderbook_data = []
        
        def on_orderbook_data(data: MarketData):
            if data.orderbook:
                orderbook_data.append(data)
                # 记录一些订单簿统计信息
                if len(orderbook_data) % 10 == 0:
                    ob = data.orderbook
                    spread = ob.get_spread()
                    mid_price = ob.get_mid_price()
                    logger.info(f"订单簿统计 - 点差: {spread}, 中间价: {mid_price}")
        
        market_router.add_callback(on_orderbook_data)
        
        ws_manager = WebSocketManager()
        ws_manager.register_adapter('binance', binance)
        
        try:
            await ws_manager.start()
            await asyncio.sleep(2)
            
            await ws_manager.subscribe_all(['BTCUSDT'])
            
            # 收集15秒的订单簿数据
            logger.info("收集15秒订单簿数据...")
            await asyncio.sleep(15)
            
            # 验证订单簿数据质量
            assert len(orderbook_data) > 0, "应该收到订单簿数据"
            
            # 检查订单簿的基本属性
            for data in orderbook_data[:5]:
                ob = data.orderbook
                assert ob is not None
                assert len(ob.bids) > 0, "买单深度应该大于0"
                assert len(ob.asks) > 0, "卖单深度应该大于0"
                assert ob.bids[0].price < ob.asks[0].price, "最佳买价应该小于最佳卖价"
                assert ob.bids[0].price > Decimal('0'), "价格应该大于0"
                assert ob.bids[0].quantity > Decimal('0'), "数量应该大于0"
            
            logger.info(f"订单簿数据质量测试通过! 收到 {len(orderbook_data)} 条订单簿更新")
            
        except Exception as e:
            logger.error(f"订单簿数据测试失败: {e}")
            raise
        finally:
            await ws_manager.stop()

@pytest.mark.integration
@pytest.mark.asyncio
class TestMultipleExchanges:
    """多交易所同时连接测试"""
    
    async def test_multiple_exchange_connections(self):
        """测试同时连接多个交易所"""
        logger.info("开始多交易所连接测试...")
        
        # 创建多个适配器
        binance = BinanceAdapter()
        # 注意：这里需要其他适配器也实现真实连接
        # bybit = BybitAdapter()
        
        ws_manager = WebSocketManager()
        market_router = MarketRouter()
        
        # 注册多个适配器
        ws_manager.register_adapter('binance', binance)
        # ws_manager.register_adapter('bybit', bybit)
        market_router.register_adapter('binance', binance)
        # market_router.register_adapter('bybit', bybit)
        
        received_data = {}
        
        def on_market_data(data: MarketData):
            exchange = data.exchange.value
            if exchange not in received_data:
                received_data[exchange] = []
            received_data[exchange].append(data)
            logger.info(f"收到 {exchange} 数据: {data.symbol}")
        
        market_router.add_callback(on_market_data)
        
        try:
            await ws_manager.start()
            await asyncio.sleep(3)
            
            status = ws_manager.get_connection_status()
            logger.info(f"多交易所连接状态: {status}")
            
            # 订阅相同的交易对
            symbols = ['BTCUSDT']
            await ws_manager.subscribe_all(symbols)
            
            # 收集20秒数据
            logger.info("收集20秒多交易所数据...")
            await asyncio.sleep(20)
            
            # 验证数据
            assert 'binance' in received_data, "应该收到币安数据"
            assert len(received_data['binance']) > 0, "币安应该收到数据"
            
            logger.info(f"多交易所测试完成! 币安: {len(received_data.get('binance', []))} 条数据")
            
        except Exception as e:
            logger.error(f"多交易所测试失败: {e}")
            raise
        finally:
            await ws_manager.stop()

if __name__ == "__main__":
    # 可以直接运行这个测试
    import asyncio
    
    async def run_all_integration_tests():
        """运行所有集成测试"""
        test_class = TestBinanceLiveConnection()
        
        print("运行币安真实连接测试...")
        await test_class.test_binance_websocket_connection()
        
        print("\n运行币安订单簿数据测试...")
        await test_class.test_binance_orderbook_data()
        
        print("\n所有集成测试完成!")
    
    asyncio.run(run_all_integration_tests())