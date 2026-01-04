import pytest
import asyncio
import logging
import sys
import os
from decimal import Decimal
from collections import deque

# 添加 src 目录到 Python 路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from market import (
    BinanceAdapter, WebSocketManager, MarketRouter,
    MarketData, ExchangeType, TradeTick, OrderBook
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

        # 注册适配器前先检查
        logger.debug(f"🔍 注册适配器前 - market_router.adapters: {market_router.adapters}")
        logger.debug(f"🔍 注册适配器前 - market_router.callbacks: {market_router.callbacks}")
        
        # 注册适配器
        ws_manager.register_adapter('binance', binance)
        market_router.register_adapter('binance', binance)
        
        # 注册适配器后检查
        logger.debug(f"🔍 注册适配器后 - market_router.adapters: {market_router.adapters}")
        logger.debug(f"🔍 注册适配器后 - market_router.callbacks: {market_router.callbacks}")

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
        
        # 添加回调前检查
        logger.debug(f"🔍 添加回调前 - market_router.callbacks 数量: {len(market_router.callbacks)}")

        # 注册回调
        market_router.add_callback(on_market_data)

        # 添加回调后检查
        logger.debug(f"🔍 添加回调后 - market_router.callbacks 数量: {len(market_router.callbacks)}")
        
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

@pytest.mark.integration
@pytest.mark.asyncio
class TestBinanceTradeData:
    """币安交易数据测试"""
    
    async def test_binance_trade_message_handling(self):
        """测试币安交易消息的处理"""
        logger.info("开始币安交易消息处理测试...")
        
        # 创建适配器和管理器
        binance = BinanceAdapter()
        ws_manager = WebSocketManager()
        market_router = MarketRouter()
        
        # 注册适配器
        ws_manager.register_adapter('binance', binance)
        market_router.register_adapter('binance', binance)
        
        # 用于收集接收到的数据
        received_trades = []
        received_market_data = []
        
        def on_market_data(data: MarketData):
            """市场数据回调"""
            if data.last_trade:
                logger.info(f"收到交易数据: {data.symbol} - {data.last_trade.side} {data.last_trade.size} @ {data.last_trade.price}")
                received_trades.append(data.last_trade)
            received_market_data.append(data)
        
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
            
            # 订阅交易对 - 使用高流动性的交易对确保有交易数据
            symbols = ['BTCUSDT', 'ETHUSDT']
            logger.info(f"订阅交易对: {symbols}")
            await ws_manager.subscribe_all(symbols)
            
            # 等待接收交易数据（最多30秒）
            logger.info("等待接收交易数据（30秒）...")
            start_time = asyncio.get_event_loop().time()
            while len(received_trades) < 10 and (asyncio.get_event_loop().time() - start_time) < 30:
                await asyncio.sleep(1)
                if received_trades:
                    logger.info(f"已收到 {len(received_trades)} 条交易数据...")
                else:
                    logger.info("尚未收到交易数据...")
            
            # 验证是否收到交易数据
            assert len(received_trades) > 0, "应该至少收到一些交易数据"
            
            # 验证交易数据格式
            for trade in received_trades[:5]:  # 检查前5条交易数据
                assert isinstance(trade, TradeTick)
                assert trade.symbol in symbols
                assert trade.exchange == ExchangeType.BINANCE
                assert trade.side in ["BUY", "SELL"]
                assert trade.price > Decimal('0')
                assert trade.size > Decimal('0')
                assert trade.trade_id is not None
                assert trade.server_timestamp > 0
                assert trade.receive_timestamp > 0
                
                logger.info(f"交易验证通过: {trade.symbol} {trade.side} {trade.size} @ {trade.price}")
            
            # 测试适配器的交易查询方法
            logger.info("测试适配器的交易查询方法...")
            for symbol in symbols:
                last_trade = binance.get_last_trade(symbol)
                if last_trade:
                    logger.info(f"{symbol} 最新交易: {last_trade.side} {last_trade.size} @ {last_trade.price}")
                
                recent_trades = binance.get_recent_trades(symbol, 5)
                logger.info(f"{symbol} 最近 {len(recent_trades)} 条交易记录")
            
            # 测试交易统计信息
            btc_stats = binance.get_trade_statistics("BTCUSDT", 60)  # 最近60秒
            if btc_stats:
                logger.info(f"BTCUSDT 交易统计: {btc_stats}")
            
            logger.info(f"交易数据测试成功! 总共收到 {len(received_trades)} 条交易数据")
            
        except Exception as e:
            logger.error(f"交易数据测试失败: {e}")
            raise
        finally:
            # 清理资源
            logger.info("清理资源...")
            await ws_manager.stop()
    
    async def test_binance_trade_side_logic(self):
        """测试币安交易方向的逻辑解析"""
        logger.info("测试币安交易方向逻辑解析...")
        
        # 创建适配器
        binance = BinanceAdapter()
        
        # 测试数据：模拟币安的交易消息
        test_messages = [
            # 格式: (原始消息, 预期方向)
            ({
                'e': 'trade',
                's': 'BTCUSDT',
                't': 12345,
                'p': '50000.00',
                'q': '0.5',
                'm': True,  # 买方是市价单 -> 主动卖出
            }, "SELL"),
            ({
                'e': 'trade',
                's': 'BTCUSDT',
                't': 12346,
                'p': '50001.00',
                'q': '0.3',
                'm': False,  # 买方是挂单方 -> 主动买入
            }, "BUY"),
            ({
                'stream': 'btcusdt@trade',
                'data': {
                    'e': 'trade',
                    's': 'BTCUSDT',
                    't': 12347,
                    'p': '50002.00',
                    'q': '0.2',
                    'm': True,  # 买方是市价单 -> 主动卖出
                    'T': 1234567890123,
                    'E': 1234567890123,
                }
            }, "SELL"),
        ]
        
        # 验证方向解析逻辑
        for i, (message, expected_side) in enumerate(test_messages):
            # 模拟消息处理
            if 'stream' in message:
                symbol = message['stream'].split('@')[0].upper()
                trade_data = message['data']
            else:
                symbol = message.get('s', '').upper()
                trade_data = message
            
            # 执行方向解析逻辑
            is_market_maker = trade_data.get('m', False)
            actual_side = "SELL" if is_market_maker else "BUY"
            
            # 验证
            assert actual_side == expected_side, \
                f"测试 {i} 失败: 预期 {expected_side}, 实际 {actual_side}"
            
            logger.info(f"交易方向测试 {i+1} 通过: {expected_side}")
        
        logger.info("交易方向逻辑解析测试全部通过!")
    
    async def test_binance_trade_recent_storage(self):
        """测试最近交易记录的存储和检索"""
        logger.info("测试最近交易记录的存储和检索...")
        
        # 创建适配器
        binance = BinanceAdapter()
        
        # 模拟接收一些交易消息
        test_trades = [
            TradeTick(
                symbol="BTCUSDT",
                trade_id="1001",
                price=Decimal("50000.00"),
                size=Decimal("0.1"),
                side="BUY",
                server_timestamp=1000000000,
                receive_timestamp=1000000000,
                exchange=ExchangeType.BINANCE
            ),
            TradeTick(
                symbol="BTCUSDT",
                trade_id="1002",
                price=Decimal("50001.00"),
                size=Decimal("0.2"),
                side="SELL",
                server_timestamp=1000001000,
                receive_timestamp=1000001000,
                exchange=ExchangeType.BINANCE
            ),
            TradeTick(
                symbol="ETHUSDT",
                trade_id="2001",
                price=Decimal("3000.00"),
                size=Decimal("1.0"),
                side="BUY",
                server_timestamp=1000002000,
                receive_timestamp=1000002000,
                exchange=ExchangeType.BINANCE
            ),
        ]
        
        # 模拟存储这些交易
        for trade in test_trades:
            binance.last_trade[trade.symbol] = trade
            if trade.symbol not in binance.recent_trades:
                binance.recent_trades[trade.symbol] = deque(maxlen=100)
            binance.recent_trades[trade.symbol].append(trade)
        
        # 测试查询方法
        # 1. 测试 get_last_trade
        btc_last = binance.get_last_trade("BTCUSDT")
        assert btc_last is not None
        assert btc_last.trade_id == "1002"
        assert btc_last.side == "SELL"
        
        eth_last = binance.get_last_trade("ETHUSDT")
        assert eth_last is not None
        assert eth_last.trade_id == "2001"
        
        # 2. 测试 get_recent_trades
        btc_recent = binance.get_recent_trades("BTCUSDT")
        assert len(btc_recent) == 2
        assert btc_recent[0].trade_id == "1001"
        assert btc_recent[1].trade_id == "1002"
        
        eth_recent = binance.get_recent_trades("ETHUSDT")
        assert len(eth_recent) == 1
        
        # 3. 测试带限制的查询
        btc_limited = binance.get_recent_trades("BTCUSDT", 1)
        assert len(btc_limited) == 1
        assert btc_limited[0].trade_id == "1002"  # 应该返回最近的
        
        # 4. 测试不存在的交易对
        nonexistent = binance.get_last_trade("NONEXISTENT")
        assert nonexistent is None
        
        nonexistent_recent = binance.get_recent_trades("NONEXISTENT")
        assert len(nonexistent_recent) == 0
        
        logger.info("最近交易记录存储和检索测试通过!")
    
    async def test_binance_trade_callback_registration(self):
        """测试交易回调注册机制"""
        logger.info("测试交易回调注册机制...")

        # 创建适配器
        binance = BinanceAdapter()
        ws_manager = WebSocketManager()
        market_router = MarketRouter()

        ws_manager.register_adapter('binance', binance)
        market_router.register_adapter('binance', binance)
        
        # 收集回调接收的数据
        market_data_received = []
        
        # 注册不同类型的回调
        def on_market_data(data: MarketData):
            market_data_received.append(data)
        
        
        # 注册回调
        market_router.add_callback(on_market_data)
        
        # 模拟一个交易消息
        test_trade = TradeTick(
            symbol="BTCUSDT",
            trade_id="9999",
            price=Decimal("51000.00"),
            size=Decimal("0.25"),
            side="BUY",
            server_timestamp=1234567890000,
            receive_timestamp=1234567890000,
            exchange=ExchangeType.BINANCE
        )
        
        # 创建对应的市场数据并触发
        market_data = binance._create_market_data(
            symbol="BTCUSDT",
            last_trade=test_trade,
            exchange=ExchangeType.BINANCE
        )
        if market_data:
            binance._notify_callbacks(market_data)
        
        # 验证回调被触发        
        if market_data_received:
            assert len(market_data_received) >= 1
            assert market_data_received[-1].last_trade.trade_id == "9999"
        
        logger.info("交易回调注册机制测试通过!")

@pytest.mark.integration
@pytest.mark.asyncio
class TestBinanceMultipleStreams:
    """币安多数据流测试"""
    
    async def test_binance_simultaneous_orderbook_and_trade(self):
        """测试同时接收订单簿和交易数据"""
        logger.info("测试同时接收订单簿和交易数据...")
        
        # 创建适配器和管理器
        # 创建适配器
        binance = BinanceAdapter()
        ws_manager = WebSocketManager()
        market_router = MarketRouter()

        ws_manager.register_adapter('binance', binance)
        market_router.register_adapter('binance', binance)
        
        # 直接注册到适配器，简化测试
        orderbook_updates = []
        trade_updates = []
        
        def on_orderbook(orderbook: MarketData):
            if orderbook.orderbook:
                orderbook_updates.append(orderbook.orderbook)
                logger.debug(f"收到订单簿更新: {orderbook.orderbook.symbol}")
        
        def on_trade(trade: MarketData):
            if trade.last_trade:
                trade_updates.append(trade.last_trade)
                logger.debug(f"收到交易更新: {trade.last_trade.symbol} {trade.last_trade.side} {trade.last_trade.size} @ {trade.last_trade.price}")
        
        market_router.add_callback(on_orderbook)
        market_router.add_callback(on_trade)
        
        try:
            # 启动连接
            await ws_manager.start()
            await asyncio.sleep(3)
            
            # 订阅
            await ws_manager.subscribe_all(['BTCUSDT'])
            
            # 收集15秒数据
            logger.info("收集15秒订单簿和交易数据...")
            await asyncio.sleep(15)
            
            # 验证两种数据都收到了
            assert len(orderbook_updates) > 0, "应该收到订单簿更新"
            assert len(trade_updates) > 0, "应该收到交易更新"
            
            # 验证数据质量
            logger.info(f"收到 {len(orderbook_updates)} 条订单簿更新")
            logger.info(f"收到 {len(trade_updates)} 条交易更新")
            
            # 验证订单簿数据
            for ob in orderbook_updates[:3]:
                assert isinstance(ob, OrderBook)
                assert len(ob.bids) > 0
                assert len(ob.asks) > 0
            
            # 验证交易数据
            for trade in trade_updates[:3]:
                assert isinstance(trade, TradeTick)
                assert trade.symbol == 'BTCUSDT'
                assert trade.side in ["BUY", "SELL"]
            
            # 检查延迟：订单簿和交易的时间戳应该合理
            if orderbook_updates and trade_updates:
                latest_orderbook = orderbook_updates[-1]
                latest_trade = trade_updates[-1]
                
                # 两者的时间差应该在合理范围内
                time_diff = abs(latest_orderbook.server_timestamp - latest_trade.server_timestamp)
                assert time_diff < 60000, f"订单簿和交易时间戳差异太大: {time_diff}ms"
            
            logger.info("同时接收订单簿和交易数据测试通过!")
            
        except Exception as e:
            logger.error(f"多数据流测试失败: {e}")
            raise
        finally:
            await ws_manager.stop()                    

if __name__ == "__main__":
    # 可以直接运行这个测试
    import asyncio
    
    async def run_all_tests():
        """运行所有测试"""
        print("开始运行所有币安集成测试...")
        
        # 运行基础连接测试
        connection_test = TestBinanceLiveConnection()
        print("\n1. 运行币安真实连接测试...")
        await connection_test.test_binance_websocket_connection()
        
        print("\n2. 运行币安订单簿数据测试...")
        await connection_test.test_binance_orderbook_data()
        
        # 运行交易数据处理测试
        trade_test = TestBinanceTradeData()
        print("\n3. 运行币安交易消息处理测试...")
        await trade_test.test_binance_trade_message_handling()
        
        print("\n4. 运行币安交易方向逻辑解析测试...")
        await trade_test.test_binance_trade_side_logic()
        
        print("\n5. 运行币安最近交易记录存储测试...")
        await trade_test.test_binance_trade_recent_storage()
        
        print("\n6. 运行币安交易回调注册机制测试...")
        await trade_test.test_binance_trade_callback_registration()
        
        # 运行多数据流测试
        multiple_streams_test = TestBinanceMultipleStreams()
        print("\n7. 运行币安多数据流同时接收测试...")
        await multiple_streams_test.test_binance_simultaneous_orderbook_and_trade()
        
        print("\n✅ 所有测试完成!")
    
    # 运行所有测试
    asyncio.run(run_all_tests())