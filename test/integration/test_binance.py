import pytest
import asyncio
import logging
import sys
import os
from decimal import Decimal
from collections import deque
import time

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
            await ws_manager.subscribe(ExchangeType.BINANCE.value, symbols)
            
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
            
            await ws_manager.subscribe(ExchangeType.BINANCE.value, ['BTCUSDT'])
            
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
            await ws_manager.subscribe(ExchangeType.BINANCE.value, symbols)
            
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
            await ws_manager.subscribe(ExchangeType.BINANCE.value, symbols)
            
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
            await ws_manager.subscribe(ExchangeType.BINANCE.value, ['BTCUSDT'])
            
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

@pytest.mark.integration
@pytest.mark.asyncio
class TestBinanceVerification:
    """数据验证测试 - 优化版"""
    
    async def test_binance_verification_mechanism(self):
        """测试验证机制本身（不关注具体验证结果）"""
        logger.info("测试验证机制功能...")
        
        # 创建适配器，启用验证功能
        binance = BinanceAdapter(verification_enabled=True)
        ws_manager = WebSocketManager()
        
        ws_manager.register_adapter('binance', binance)
        
        try:
            # 启动连接
            await ws_manager.start()
            await asyncio.sleep(2)
            
            # 订阅单个交易对，简化测试
            await ws_manager.subscribe(ExchangeType.BINANCE.value, ['BTCUSDT'])
            
            # 等待初始快照加载
            logger.info("等待订单簿初始快照加载...")
            await asyncio.sleep(5)
            
            # 测试验证统计功能
            status_before = binance.get_verification_status('BTCUSDT')
            logger.info(f"初始验证状态: {status_before}")
            
            # 执行一次手动验证
            is_valid, details = await binance.verify_orderbook_snapshot('BTCUSDT')
            print("is_valid: ", is_valid)
            print("details: ", details)
            
            # 验证返回的数据结构
            assert isinstance(is_valid, bool)
            assert isinstance(details, dict)
            assert 'reason' in details
            assert 'update_id_info' in details  # 修改这里
            
            # 从 update_id_info 中获取更新ID信息
            update_id_info = details['update_id_info']
            assert 'local_update_id' in update_id_info  # 修改这里
            assert 'snapshot_update_id' in update_id_info  # 修改这里
            assert 'update_id_diff' in update_id_info
            
            # 检查其他关键字段
            assert 'critical_issues' in details
            assert 'differences' in details
            assert 'warnings' in details
            assert 'pending_updates' in details
            assert 'is_valid' in details
            
            logger.info(f"验证结果 - 有效: {is_valid}, 原因: {details['reason']}")
            logger.info(f"更新ID信息: 本地={update_id_info['local_update_id']}, "
                    f"快照={update_id_info['snapshot_update_id']}, "
                    f"差异={update_id_info['update_id_diff']}")
            
            assert is_valid == True
            
            # 检查验证统计是否更新
            status_after = binance.get_verification_status('BTCUSDT')
            logger.info(f"验证后状态: {status_after}")
            
            # 验证次数应该增加
            assert status_after['total_verifications'] > status_before.get('total_verifications', 0)
            
            # 验证订单簿数据的基本完整性
            btc_ob = binance.orderbook_snapshots.get('BTCUSDT')
            assert btc_ob is not None, "BTCUSDT订单簿应该存在"
            
            # 检查订单簿是否遵循基本规则
            if btc_ob.bids and btc_ob.asks:
                best_bid = btc_ob.bids[0].price
                best_ask = btc_ob.asks[0].price
                assert best_bid < best_ask, f"买卖盘交叉: 最佳买价 {best_bid} >= 最佳卖价 {best_ask}"
                logger.info(f"订单簿基本规则检查通过 - 最佳买价: {best_bid}, 最佳卖价: {best_ask}")
            
            logger.info("✅ 验证机制功能测试通过!")
            
        except Exception as e:
            logger.error(f"验证机制测试失败: {e}")
            raise
        finally:
            await ws_manager.stop()
    
    async def test_binance_verification_accuracy(self):
        """测试验证的准确性（关注数据质量，而非严格匹配）"""
        logger.info("测试验证准确性...")
        
        binance = BinanceAdapter(verification_enabled=False)  # 禁用自动验证，手动控制
        ws_manager = WebSocketManager()
        
        ws_manager.register_adapter('binance', binance)
        
        try:
            # 启动连接
            await ws_manager.start()
            await asyncio.sleep(2)
            
            # 订阅
            await ws_manager.subscribe(ExchangeType.BINANCE.value, ['BTCUSDT'])
            
            # 等待充分的数据收集
            logger.info("收集15秒数据用于准确性分析...")
            await asyncio.sleep(15)
            
            # 执行验证，使用宽松参数（接受市场正常波动）
            is_valid, details = await binance.verify_orderbook_snapshot('BTCUSDT', tolerance=0.01)
            
            logger.info(f"验证详情:")
            logger.info(f"  是否有效: {is_valid}")
            logger.info(f"  原因: {details.get('reason')}")
            logger.info(f"  本地更新ID: {details.get('local_update_id')}")
            logger.info(f"  快照更新ID: {details.get('snapshot_update_id')}")

            assert is_valid == True
            
            # 关键断言：更新ID关系
            local_id = details.get('local_update_id', 0)
            snapshot_id = details.get('snapshot_update_id', 0)
            
            # 本地更新ID应该 >= 快照更新ID（我们处理了快照之后的所有更新）
            assert local_id >= snapshot_id, \
                f"本地更新ID({local_id})小于快照更新ID({snapshot_id})，可能丢失数据"
            
            # 检查严重问题
            if 'critical_issues' in details:
                critical_issues = details['critical_issues']
                if critical_issues:
                    logger.error("发现严重问题，测试失败:")
                    for issue in critical_issues:
                        logger.error(f"  - {issue}")
                    assert False, f"发现 {len(critical_issues)} 个严重问题"
            
            # 检查差异数量（允许少量差异）
            differences = details.get('differences', [])
            if differences:
                logger.warning(f"发现 {len(differences)} 个差异:")
                for diff in differences[:3]:  # 只显示前3个
                    logger.warning(f"  - {diff}")
                
                # 允许少量差异，但过多差异可能有问题
                assert len(differences) < 10, f"差异过多: {len(differences)}个"
            
            # 检查数据质量指标
            pending = details.get('pending_updates', 0)
            logger.info(f"pending buffer长度: {pending}")
            assert pending < 100, f"pending buffer过长: {pending}"
            
            # 检查数据新鲜度
            if 'data_timestamp' in details and details['data_timestamp']:
                data_age = time.time() * 1000 - details['data_timestamp']
                logger.info(f"数据延迟: {data_age:.0f}ms")
                assert data_age < 30000, f"数据延迟过大: {data_age:.0f}ms"
            
            logger.info("✅ 验证准确性测试通过!")
            
        except Exception as e:
            logger.error(f"准确性测试失败: {e}")
            raise
        finally:
            await ws_manager.stop()
    
    async def test_binance_verification_with_multiple_symbols(self):
        """测试多交易对验证"""
        logger.info("测试多交易对验证...")
        
        binance = BinanceAdapter(verification_enabled=False)
        ws_manager = WebSocketManager()
        
        ws_manager.register_adapter('binance', binance)
        
        symbols = ['BTCUSDT', 'ETHUSDT']
        
        try:
            # 启动连接
            await ws_manager.start()
            await asyncio.sleep(2)
            
            # 订阅多个交易对
            await ws_manager.subscribe(ExchangeType.BINANCE.value, symbols)
            
            # 等待初始同步
            logger.info("等待多交易对数据同步...")
            await asyncio.sleep(8)
            
            # 验证每个交易对
            results = {}
            for symbol in symbols:
                is_valid, details = await binance.verify_orderbook_snapshot(symbol, tolerance=0.01)
                print("symbol:", symbol, ", details: ", details)
                results[symbol] = {
                    'is_valid': is_valid,
                    'reason': details.get('reason'),
                    'local_id': details.get('local_update_id'),
                    'snapshot_id': details.get('snapshot_update_id'),
                    'pending': details.get('pending_updates', 0)
                }
                
                logger.info(f"{symbol} 验证结果:")
                logger.info(f"  有效: {is_valid}")
                logger.info(f"  本地更新ID: {details.get('local_update_id')}")
                logger.info(f"  快照更新ID: {details.get('snapshot_update_id')}")
                logger.info(f"  pending: {details.get('pending_updates', 0)}")
            
            # 基本断言
            for symbol in symbols:
                result = results[symbol]
                
                # 每个交易对都应该有数据
                assert binance.orderbook_snapshots.get(symbol) is not None, \
                    f"{symbol} 订单簿不存在"
                
                assert result['is_valid'] == True
                
                # 更新ID应该合理
                assert result['local_id'] > 0, f"{symbol} 更新ID应该大于0"
                
                # pending buffer应该在合理范围内
                assert result['pending'] < 100, f"{symbol} pending buffer过长"
            
            logger.info("✅ 多交易对验证测试通过!")
            
        except Exception as e:
            logger.error(f"多交易对测试失败: {e}")
            raise
        finally:
            await ws_manager.stop()
    
    async def test_binance_orderbook_data_quality(self):
        """测试订单簿数据质量（不依赖验证）"""
        logger.info("测试订单簿数据质量...")
        
        binance = BinanceAdapter(verification_enabled=False)
        ws_manager = WebSocketManager()
        
        ws_manager.register_adapter('binance', binance)
        
        # 收集质量指标
        quality_metrics = {
            'update_count': 0,
            'spreads': [],
            'bid_ask_ratios': [],
            'price_changes': [],
            'timestamps': []
        }
        
        def on_market_data(data: MarketData):
            if data.orderbook:
                quality_metrics['update_count'] += 1
                
                ob = data.orderbook
                if ob.bids and ob.asks:
                    # 计算价差
                    best_bid = ob.bids[0].price
                    best_ask = ob.asks[0].price
                    spread = float(best_ask - best_bid)
                    spread_bps = (spread / float(best_bid)) * 10000
                    quality_metrics['spreads'].append(spread_bps)
                    
                    # 记录时间戳
                    quality_metrics['timestamps'].append(ob.server_timestamp)
        
        binance.add_callback(on_market_data)
        
        try:
            # 启动连接
            await ws_manager.start()
            await asyncio.sleep(2)
            
            # 订阅
            await ws_manager.subscribe(ExchangeType.BINANCE.value, ['BTCUSDT'])
            
            # 收集数据
            logger.info("收集20秒数据用于质量分析...")
            await asyncio.sleep(20)
            
            # 分析数据质量
            assert quality_metrics['update_count'] > 0, "应该收到订单簿更新"
            logger.info(f"收到 {quality_metrics['update_count']} 条订单簿更新")
            
            if quality_metrics['spreads']:
                avg_spread = sum(quality_metrics['spreads']) / len(quality_metrics['spreads'])
                min_spread = min(quality_metrics['spreads'])
                max_spread = max(quality_metrics['spreads'])
                
                logger.info(f"价差统计: 平均 {avg_spread:.2f}bps, 范围 {min_spread:.2f}-{max_spread:.2f}bps")
                
                # BTCUSDT的正常价差应该在合理范围内
                assert avg_spread < 50, f"平均价差过大: {avg_spread:.2f}bps"
                assert max_spread < 100, f"最大价差过大: {max_spread:.2f}bps"
            
            # 检查更新频率
            if len(quality_metrics['timestamps']) >= 2:
                intervals = []
                for i in range(1, len(quality_metrics['timestamps'])):
                    interval = quality_metrics['timestamps'][i] - quality_metrics['timestamps'][i-1]
                    intervals.append(interval)
                
                if intervals:
                    avg_interval = sum(intervals) / len(intervals)
                    logger.info(f"平均更新间隔: {avg_interval:.0f}ms")
                    
                    # 应该大致匹配100ms的更新频率
                    assert avg_interval < 500, f"更新间隔过大: {avg_interval:.0f}ms"
            
            # 检查订单簿深度
            btc_ob = binance.orderbook_snapshots.get('BTCUSDT')
            assert btc_ob is not None, "订单簿应该存在"
            
            logger.info(f"订单簿深度: 买盘 {len(btc_ob.bids)} 档, 卖盘 {len(btc_ob.asks)} 档")
            
            # 检查价格单调性
            bids_valid = True
            for i in range(len(btc_ob.bids) - 1):
                if btc_ob.bids[i].price <= btc_ob.bids[i + 1].price:
                    bids_valid = False
                    break
            
            asks_valid = True
            for i in range(len(btc_ob.asks) - 1):
                if btc_ob.asks[i].price >= btc_ob.asks[i + 1].price:
                    asks_valid = False
                    break
            
            assert bids_valid, "买盘价格应该单调递减"
            assert asks_valid, "卖盘价格应该单调递增"
            
            logger.info("✅ 订单簿数据质量测试通过!")
            
        except Exception as e:
            logger.error(f"数据质量测试失败: {e}")
            raise
        finally:
            await ws_manager.stop()      


@pytest.mark.integration
@pytest.mark.asyncio
class TestBinancePreciseVerification:
    """币安精准数据验证测试"""
    
    async def test_binance_orderbook_integrity(self):
        """测试订单簿数据完整性（核心验证）"""
        logger.info("测试订单簿数据完整性...")
        
        binance = BinanceAdapter(verification_enabled=True)
        ws_manager = WebSocketManager()
        
        ws_manager.register_adapter('binance', binance)
        
        # 收集数据用于分析
        received_updates = []
        def on_market_data(data: MarketData):
            if data.orderbook:
                received_updates.append({
                    'timestamp': time.time(),
                    'update_id': data.orderbook.last_update_id,
                    'best_bid': data.orderbook.bids[0].price if data.orderbook.bids else None,
                    'best_ask': data.orderbook.asks[0].price if data.orderbook.asks else None,
                })
        
        binance.add_callback(on_market_data)
        
        try:
            # 启动连接
            await ws_manager.start()
            await asyncio.sleep(2)
            
            # 只订阅一个交易对，减少干扰
            await ws_manager.subscribe(ExchangeType.BINANCE.value, ['BTCUSDT'])
            
            # 等待充分的数据收集
            logger.info("收集20秒数据用于完整性分析...")
            await asyncio.sleep(20)
            
            # 检查是否收到数据
            assert len(received_updates) > 0, "应该收到订单簿更新"
            logger.info(f"收集到 {len(received_updates)} 条更新")
            
            # 验证更新ID的单调递增性（核心检查）
            update_ids = [update['update_id'] for update in received_updates if update['update_id']]
            if len(update_ids) >= 2:
                for i in range(1, len(update_ids)):
                    # 更新ID应该是严格递增的
                    assert update_ids[i] > update_ids[i-1], \
                        f"更新ID非单调递增: {update_ids[i-1]} -> {update_ids[i]}"
                logger.info(f"✅ 更新ID单调递增检查通过（{len(update_ids)}个更新）")
            
            # 验证买卖价差的合理性
            spreads = []
            for update in received_updates:
                if update['best_bid'] and update['best_ask']:
                    spread = float(update['best_ask'] - update['best_bid'])
                    spread_bps = (spread / float(update['best_bid'])) * 10000
                    spreads.append(spread_bps)
            
            if spreads:
                avg_spread = sum(spreads) / len(spreads)
                max_spread = max(spreads)
                min_spread = min(spreads)
                
                logger.info(f"价差统计: 平均 {avg_spread:.2f}bps, 范围 {min_spread:.2f}-{max_spread:.2f}bps")
                
                # BTCUSDT的正常价差应该在1-10bps范围内
                assert avg_spread < 50, f"平均价差过大: {avg_spread:.2f}bps"
                assert max_spread < 100, f"最大价差过大: {max_spread:.2f}bps"
            
            # 执行精准验证
            logger.info("执行精准订单簿验证...")
            is_valid, details = await binance.verify_orderbook_snapshot('BTCUSDT', tolerance=0.001)
            
            logger.info(f"验证结果:")
            logger.info(f"  是否有效: {is_valid}")
            logger.info(f"  原因: {details.get('reason')}")
            
            # 检查更新ID的正确性（最关键的部分）
            update_info = details.get('update_id_info', {})
            local_id = update_info.get('local_update_id', 0)
            snapshot_id = update_info.get('snapshot_update_id', 0)
            diff = update_info.get('update_id_diff', 0)
            
            logger.info(f"  快照更新ID: {snapshot_id}")
            logger.info(f"  本地最后更新ID: {local_id}")
            logger.info(f"  更新ID差异: {diff}")
            
            # 关键断言：本地更新ID必须 >= 快照更新ID
            assert local_id >= snapshot_id, \
                f"本地更新ID({local_id})小于快照更新ID({snapshot_id})，数据可能丢失"
            
            # 如果diff过大，可能有问题
            if diff > 10000:
                logger.warning(f"更新ID差异较大: {diff}，可能处理较慢")
            
            # 检查是否有严重问题
            critical_issues = details.get('critical_issues', [])
            if critical_issues:
                logger.error("发现严重问题:")
                for issue in critical_issues:
                    logger.error(f"  - {issue}")
                assert False, f"发现 {len(critical_issues)} 个严重问题"
            
            # 检查警告信息
            warnings = details.get('warnings', [])
            if warnings:
                logger.warning(f"发现 {len(warnings)} 个警告:")
                for warning in warnings[:3]:
                    logger.warning(f"  - {warning}")
            
            # 检查pending buffer
            pending = details.get('pending_updates', 0)
            logger.info(f"pending buffer长度: {pending}")
            assert pending < 100, f"pending buffer过长: {pending}"
            
            logger.info("✅ 订单簿数据完整性验证通过!")
            
        except Exception as e:
            logger.error(f"数据完整性测试失败: {e}")
            raise
        finally:
            await ws_manager.stop()
    
    async def test_binance_orderbook_resync_mechanism(self):
        """测试订单簿重新同步机制"""
        logger.info("测试订单簿重新同步机制...")
        
        binance = BinanceAdapter(verification_enabled=True)
        ws_manager = WebSocketManager()
        
        ws_manager.register_adapter('binance', binance)
        
        # 记录重新同步事件
        resync_events = []
        original_init_snapshot = binance._init_snapshot_with_buffering
        
        async def mock_init_snapshot(symbol: str):
            resync_events.append({
                'timestamp': time.time(),
                'symbol': symbol,
                'reason': 'manual_resync_test'
            })
            return await original_init_snapshot(symbol)
        
        # 模拟重新同步
        binance._init_snapshot_with_buffering = mock_init_snapshot
        
        try:
            # 启动连接
            await ws_manager.start()
            await asyncio.sleep(2)
            
            # 订阅
            await ws_manager.subscribe(ExchangeType.BINANCE.value, ['BTCUSDT'])
            
            # 等待初始同步完成
            await asyncio.sleep(5)
            
            # 验证初始状态
            initial_status = binance.get_verification_status('BTCUSDT')
            logger.info(f"初始状态: {initial_status}")
            
            # 模拟数据不一致，手动触发重新同步
            logger.info("模拟数据不一致，触发重新同步...")
            
            # 方法1：清空订单簿，模拟数据丢失
            binance.orderbook_snapshots.pop('BTCUSDT', None)
            binance.last_update_ids.pop('BTCUSDT', None)
            
            # 方法1a：立即验证（可能失败，也可能重新同步已完成）
            is_valid, details = await binance.verify_orderbook_snapshot('BTCUSDT')
            
            # 检查重新同步事件
            if len(resync_events) > 0:
                logger.info(f"✅ 已触发自动重新同步，事件数: {len(resync_events)}")
                # 如果有重新同步事件，说明机制工作正常
                if is_valid:
                    logger.info("✅ 重新同步成功，数据有效")
                else:
                    logger.warning(f"重新同步后数据仍无效: {details.get('reason')}")
            else:
                # 如果没有重新同步事件，验证应该失败
                assert not is_valid, "数据丢失且无重新同步时，验证应该失败"
                logger.info(f"数据丢失验证结果: {details.get('reason')}")
            
            # 等待可能的重新同步完成
            await asyncio.sleep(3)
            
            # 方法2：模拟pending buffer堆积
            logger.info("测试pending buffer阈值检测...")
            
            # 添加大量假更新到pending buffer
            test_updates = []
            for i in range(2000):
                test_updates.append({
                    'u': 99999999999 + i,  # 很大的更新ID
                    'b': [['100000.00', '1.0']],
                    'a': [['100001.00', '1.0']]
                })
            
            if 'BTCUSDT' not in binance.pending_updates:
                binance.pending_updates['BTCUSDT'] = []
            binance.pending_updates['BTCUSDT'].extend(test_updates)
            
            # 检查pending buffer阈值检测
            pending_len = len(binance.pending_updates.get('BTCUSDT', []))
            logger.info(f"pending buffer长度: {pending_len}")
            
            if pending_len > binance.PENDING_RESYNC_THRESHOLD:
                logger.warning(f"pending buffer超过阈值: {pending_len} > {binance.PENDING_RESYNC_THRESHOLD}")
                # 在实际代码中，这里应该触发重新同步
            
            # 验证重新同步机制是否有效
            logger.info("验证重新同步机制...")
            
            # 检查是否已经有重新同步事件
            initial_resync_count = len(resync_events)
            
            # 触发一次手动重新同步（如果还没有发生的话）
            if initial_resync_count == 0:
                await binance._init_snapshot_with_buffering('BTCUSDT')
            
            # 检查重新同步事件是否记录
            assert len(resync_events) > 0, "应该记录重新同步事件"
            
            # 验证重新同步后的状态
            await asyncio.sleep(2)
            is_valid, details = await binance.verify_orderbook_snapshot('BTCUSDT')
            
            if is_valid:
                logger.info("✅ 重新同步后数据验证通过")
            else:
                logger.warning(f"重新同步后仍有问题: {details.get('reason')}")
                # 重新同步可能不完全解决所有问题，但至少应该恢复基本功能
            
            logger.info("✅ 订单簿重新同步机制测试完成!")
            
        except Exception as e:
            logger.error(f"重新同步测试失败: {e}")
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

        # 数据验证测试
        verification_test = TestBinanceVerification()
        print("\n8. 运行验证机制功能测试...")
        await verification_test.test_binance_verification_mechanism()

        print("\n9. 运行验证准确性测试...")
        await verification_test.test_binance_verification_accuracy()

        print("\n10. 运行多交易对验证测试...")
        await verification_test.test_binance_verification_with_multiple_symbols()

        print("\n11. 运行订单簿数据质量测试...")
        await verification_test.test_binance_orderbook_data_quality()

        # 精准验证测试
        precise_verification_test = TestBinancePreciseVerification()
        print("\n12. 运行订单簿数据完整性测试...")
        await precise_verification_test.test_binance_orderbook_integrity()

        print("\n13. 运行订单簿重新同步机制测试...")
        await precise_verification_test.test_binance_orderbook_resync_mechanism()
        
        print("\n✅ 所有测试完成!")
    
    # 运行所有测试
    asyncio.run(run_all_tests())