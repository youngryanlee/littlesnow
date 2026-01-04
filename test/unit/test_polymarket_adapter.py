import pytest
import asyncio
import logging
from unittest.mock import Mock, patch, AsyncMock, MagicMock, call
from decimal import Decimal
from datetime import datetime, timezone
from collections import deque, defaultdict
import sys
import os

# 添加 src 目录到 Python 路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from market.adapter.polymarket_adapter import PolymarketAdapter, SubscriptionType
from market.core.data_models import MarketData, OrderBook, OrderBookLevel, ExchangeType, MarketType

# 配置测试日志
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

class TestPolymarketWebSocketAdapter:
    """PolymarketAdapter 单元测试 - 适配多connector版本"""
    
    @pytest.fixture
    def adapter(self):
        """创建适配器实例，mock多个connector"""
        # Mock WebSocketConnector 类
        with patch('market.adapter.polymarket_adapter.WebSocketConnector') as mock_ws_class:
            # 创建4个mock connector，对应orderbook、trades、prices、comments
            mock_connectors = {
                SubscriptionType.ORDERBOOK: MagicMock(),
                SubscriptionType.TRADE: MagicMock(),
                SubscriptionType.PRICE: MagicMock(),
                SubscriptionType.COMMENT: MagicMock()
            }
            
            # 🔧 关键修复：创建字符串到枚举的映射
            type_map = {
                'orderbook': SubscriptionType.ORDERBOOK,
                'trades': SubscriptionType.TRADE,
                'prices': SubscriptionType.PRICE,
                'comments': SubscriptionType.COMMENT
            }
            
            # 让WebSocketConnector构造函数返回正确的mock对象
            def create_mock_connector(url, on_message, on_error, **kwargs):
                connector_type_str = kwargs.get('connector_type', 'orderbook')
                connector_type = type_map[connector_type_str]  # 将字符串转换为枚举
                return mock_connectors[connector_type]
            
            mock_ws_class.side_effect = create_mock_connector
            
            # 创建适配器
            adapter = PolymarketAdapter()
            
            # 确保适配器使用了我们的mock connectors
            adapter.connectors = mock_connectors
            
            # 设置一些默认的mock行为
            for connector in mock_connectors.values():
                connector.connect = AsyncMock(return_value=True)
                connector.disconnect = AsyncMock()
                connector.send_json = AsyncMock()
                connector.get_connection_info = MagicMock(return_value={"status": "connected"})
            
            return adapter
    
    @pytest.fixture
    def sample_orderbook_message(self):
        """提供样本订单簿消息"""
        return {
            "asset_id": "1234567890abcdef1234567890abcdef12345678",
            "market": "0x1234567890abcdef1234567890abcdef12345678",
            "timestamp": "1640995200000",  # 使用时间戳而不是序列号
            "bids": [{"price": "0.65", "size": "1000"}, {"price": "0.64", "size": "500"}],
            "asks": [{"price": "0.66", "size": "800"}, {"price": "0.67", "size": "1200"}],
            "event_type": "book"
        }
    
    @pytest.fixture
    def sample_trade_message(self):
        """提供样本交易消息"""
        return {
            "asset_id": "1234567890abcdef1234567890abcdef12345678",
            "market": "0x1234567890abcdef1234567890abcdef12345678",
            "price": "0.65",
            "size": "100",
            "side": "buy",
            "timestamp": "1640995200000",
            "event_type": "trade"
        }
    
    @pytest.fixture
    def sample_price_change_message(self):
        """提供样本价格变动消息"""
        return {
            "market": "0x1234567890abcdef1234567890abcdef12345678",
            "price_changes": [
                {
                    "asset_id": "test_asset_1",
                    "price": "0.022",
                    "size": "4230.32",
                    "side": "SELL",
                    "hash": "test_hash1",
                    "best_bid": "0.002",
                    "best_ask": "0.003"
                },
                {
                    "asset_id": "test_asset_2",
                    "price": "0.078",
                    "size": "230.32",
                    "side": "BUY",
                    "hash": "test_hash2",
                    "best_bid": "0.002",
                    "best_ask": "0.003"
                }
            ],
            "timestamp": "1640995200000",
            "event_type": "price_change"
        }
    
    def test_initialization(self, adapter):
        """测试适配器初始化 - 适配新的性能监控结构"""
        # 基本属性测试
        assert adapter.name == "polymarket"
        assert adapter.exchange_type == ExchangeType.POLYMARKET
        assert adapter.is_connected == False
        assert len(adapter.callbacks) == 0
        assert len(adapter.subscribed_symbols) == 0
        
        # 检查多个connector
        assert SubscriptionType.ORDERBOOK in adapter.connectors
        assert SubscriptionType.TRADE in adapter.connectors
        assert SubscriptionType.PRICE in adapter.connectors
        assert SubscriptionType.COMMENT in adapter.connectors
        
        # 🔄 更新：检查新的性能监控结构
        assert adapter.message_count == 0
        assert adapter.last_message_time is None
        assert adapter.clock_offset_ms == 0
        
        # 检查PerformanceMonitor实例
        assert hasattr(adapter, 'monitor')
        assert adapter.monitor is not None
        assert adapter.monitor.window_size == 1000  # 默认值
        
        # 检查realtime_stats结构
        assert "orderbook" in adapter.monitor.realtime_stats
        assert "last_trade_price" in adapter.monitor.realtime_stats
        assert "price_change" in adapter.monitor.realtime_stats
        assert "all" in adapter.monitor.realtime_stats
        
        # 检查每个统计项的初始化值
        for msg_type in ["orderbook", "last_trade_price", "price_change", "all"]:
            stats = adapter.monitor.realtime_stats[msg_type]
            assert stats["count"] == 0
            assert stats["last_time"] is None
            assert stats["latency_ewma"] == 0.0
            assert stats["latency_p50"] == 0.0
            assert stats["latency_p95"] == 0.0
            assert stats["latency_p99"] == 0.0
            assert stats["latency_min"] == float('inf')
            assert stats["latency_max"] == 0.0
            assert stats["throughput_1s"] == 0.0
            assert stats["throughput_1m"] == 0.0
            assert stats["last_update"] is None
            assert stats["errors"] == 0
        
        # 🔧 修改：检查latency_history结构（defaultdict不会预先创建键）
        assert isinstance(adapter.monitor.latency_history, defaultdict)
        
        # 检查默认工厂函数创建的deque属性
        # 注意：defaultdict只在访问时才创建键，所以初始时可能是空的
        for msg_type in ["orderbook", "last_trade_price", "price_change", "all"]:
            # 访问键以创建默认的deque
            deque_obj = adapter.monitor.latency_history[msg_type]
            assert isinstance(deque_obj, deque)
            assert deque_obj.maxlen == adapter.monitor.window_size
            assert len(deque_obj) == 0  # 初始为空
        
        # 🔧 修改：检查其他数据结构是否正确初始化
        assert isinstance(adapter.orderbook_snapshots, dict)
        assert isinstance(adapter.last_trade_prices, dict)
        assert isinstance(adapter.price_changes, dict)
        assert isinstance(adapter.last_prices, dict)
        assert isinstance(adapter.best_prices, dict)
        assert isinstance(adapter.market_cache, dict)
        assert isinstance(adapter.token_cache, dict)
        assert adapter.cache_ttl_seconds == 3600

    def test_performance_monitor_update(self, adapter):
        """测试性能监控器更新功能"""
        # 模拟更新延迟统计
        adapter._update_latency_stats("orderbook", 50.0, 1234567890000)
        
        # 检查统计更新
        stats = adapter.monitor.realtime_stats["orderbook"]
        assert stats["count"] == 1
        assert stats["latency_ewma"] > 0  # 因为0.9*0 + 50*0.1 = 5.0
        assert stats["latency_min"] == 50.0
        assert stats["latency_max"] == 50.0
        assert stats["last_time"] is not None
        
        # 检查延迟历史记录
        assert len(adapter.monitor.latency_history["orderbook"]) == 1
        assert adapter.monitor.latency_history["orderbook"][0] == 50.0
        
        # 更新"all"统计
        all_stats = adapter.monitor.realtime_stats["all"]
        assert all_stats["count"] == 1
        assert all_stats["latency_ewma"] > 0

    def test_latency_calculation(self, adapter):
        """测试延迟计算 - 修正版"""
        base_receive_ts = 1234567890050
        
        # 测试1：正常延迟
        normal_data = {
            "timestamp": "1234567890000",
            "event_type": "last_trade_price",
            "asset_id": "test-asset-1"
        }
        latency = adapter._calculate_network_latency(normal_data, base_receive_ts)
        assert latency == 50.0, f"期望50.0，实际{latency}"
        
        # 测试2：负延迟
        negative_data = {
            "timestamp": "1234567890100",  # 比接收时间晚50ms
            "event_type": "last_trade_price",
            "asset_id": "test-asset-2"
        }
        latency = adapter._calculate_network_latency(negative_data, base_receive_ts)
        assert latency == -50.0, f"期望-50.0，实际{latency}"
        
        # 测试3：缺少时间戳
        no_timestamp_data = {
            "event_type": "last_trade_price",
            "asset_id": "test-asset-3"
        }
        latency = adapter._calculate_network_latency(no_timestamp_data, base_receive_ts)
        assert latency is None, f"期望None，实际{latency}"
        
        # 测试4：异常高延迟（修正计算错误）
        # 原错误：1234567890050 - 1234467890000 = 100000050，不是100050
        high_latency_data = {
            "timestamp": "1234467890000",
            "event_type": "last_trade_price",
            "asset_id": "test-asset-4"
        }
        latency = adapter._calculate_network_latency(high_latency_data, base_receive_ts)
        expected_high_latency = 100000050  # 正确的计算结果
        assert latency == expected_high_latency, f"期望{expected_high_latency}，实际{latency}"
        
        # 测试5：无效时间戳格式
        invalid_timestamp_data = {
            "timestamp": "not-a-number",
            "event_type": "last_trade_price",
            "asset_id": "test-asset-5"
        }
        latency = adapter._calculate_network_latency(invalid_timestamp_data, base_receive_ts)
        assert latency is None, f"期望None，实际{latency}"
        
        # 测试6：正好边界值（10秒）
        boundary_data = {
            "timestamp": str(base_receive_ts - 10000),  # 正好10秒前
            "event_type": "last_trade_price",
            "asset_id": "test-asset-6"
        }
        latency = adapter._calculate_network_latency(boundary_data, base_receive_ts)
        assert latency == 10000, f"期望10000，实际{latency}"
        
        # 测试7：零延迟
        zero_data = {
            "timestamp": str(base_receive_ts),  # 与接收时间相同
            "event_type": "last_trade_price",
            "asset_id": "test-asset-7"
        }
        latency = adapter._calculate_network_latency(zero_data, base_receive_ts)
        assert latency == 0, f"期望0，实际{latency}"

    def test_message_processing_with_latency(self, adapter):
        """测试带延迟的消息处理"""
        # 模拟一个交易消息
        trade_data = {
            "event_type": "last_trade_price",
            "asset_id": "test-asset-1",
            "market": "0x1234567890abcdef1234567890abcdef12345678",
            "price": "0.65",
            "size": "1000",
            "side": "BUY",
            "timestamp": "1234567890000",
            "id": "trade-123"
        }
        
        receive_time = datetime.now(timezone.utc)
        receive_timestamp_ms = int(receive_time.timestamp() * 1000)
        
        # 处理消息
        adapter._handle_raw_message(trade_data)
        
        # 检查消息计数
        assert adapter.message_count == 1
        
        # 检查延迟统计被更新
        stats = adapter.monitor.realtime_stats["last_trade_price"]
        assert stats["count"] == 1
        assert stats["latency_ewma"] > 0
        
        # 检查交易缓存被更新
        assert "test-asset-1" in adapter.last_trade_prices
        trade_price = adapter.last_trade_prices["test-asset-1"]
        print("trade_price: ", trade_price)
        assert trade_price.price == Decimal("0.65")
        assert trade_price.size == Decimal("1000")
        assert trade_price.side == "BUY"
        assert trade_price.server_timestamp == 1234567890000
        assert trade_price.receive_timestamp == receive_timestamp_ms

    def test_monitor_initialization_values(self):
        """测试性能监控器初始化值"""
        # 创建适配器
        adapter = PolymarketAdapter()
        
        # 检查默认窗口大小
        assert adapter.monitor.window_size == 1000
        
        # 检查realtime_stats结构完整性
        expected_keys = ["orderbook", "last_trade_price", "price_change", "all"]
        for key in expected_keys:
            assert key in adapter.monitor.realtime_stats
            
            stats = adapter.monitor.realtime_stats[key]
            expected_stat_keys = [
                "count", "last_time", "latency_ewma", "latency_p50",
                "latency_p95", "latency_p99", "latency_min", "latency_max",
                "throughput_1s", "throughput_1m", "last_update", "errors"
            ]
            
            for stat_key in expected_stat_keys:
                assert stat_key in stats
                
        # 注意：latency_history是defaultdict，初始为空
        # 我们只需要检查它被正确初始化为defaultdict即可
        assert isinstance(adapter.monitor.latency_history, defaultdict)
        # 可以检查默认工厂函数是否设置正确
        assert adapter.monitor.latency_history.default_factory is not None
        
        # 或者检查访问某个键时是否能正确创建deque
        test_deque = adapter.monitor.latency_history["test"]
        assert isinstance(test_deque, deque)
        assert test_deque.maxlen == 1000

    def test_performance_monitor_edge_cases(self, adapter):
        """测试性能监控器边界情况"""
        # 测试大量消息处理
        for i in range(1500):  # 超过窗口大小
            adapter._update_latency_stats("orderbook", float(i), 1234567890000 + i)

        # 检查窗口大小限制
        assert len(adapter.monitor.latency_history["orderbook"]) == 1000

        # 但是计数是1500
        assert adapter.monitor.realtime_stats["orderbook"]["count"] == 1500

        # 测试不同消息类型的独立统计
        adapter._update_latency_stats("orderbook", 100.0, 1234567890000)
        adapter._update_latency_stats("last_trade_price", 50.0, 1234567890000)

        assert adapter.monitor.realtime_stats["orderbook"]["count"] == 1501
        assert adapter.monitor.realtime_stats["last_trade_price"]["count"] == 1
        assert adapter.monitor.realtime_stats["all"]["count"] == 1502

        # 测试EWMA计算 - 使用预定义的消息类型
        # 重置一个消息类型的统计
        adapter.monitor.realtime_stats["price_change"] = adapter.monitor._init_message_stats()
        
        # 第一个值：0.9*0 + 100*0.1 = 10
        # 第二个值：0.9*10 + 200*0.1 = 9 + 20 = 29
        adapter._update_latency_stats("price_change", 100.0, 1234567890000)
        adapter._update_latency_stats("price_change", 200.0, 1234567890001)

        stats = adapter.monitor.realtime_stats["price_change"]
        # EWMA计算验证
        expected_ewma_1 = 100.0 * 0.1  # 第一个值
        # 由于EWMA的alpha=0.9，第二个值计算：0.9*10 + 200*0.1 = 9 + 20 = 29
        expected_ewma_2 = 100.0 * 0.1 * 0.9 + 200.0 * 0.1  # 29.0
        
        assert abs(stats["latency_ewma"] - expected_ewma_2) < 0.001 
    
    @pytest.mark.asyncio
    async def test_connect_success(self, adapter):
        """测试成功连接所有WebSocket connector"""
        # 设置所有connector连接成功
        for connector in adapter.connectors.values():
            connector.connect = AsyncMock(return_value=True)
        
        # 🔧 修复：Mock 其他可能调用的方法
        adapter._resubscribe_all = AsyncMock()
        adapter._performance_monitor = AsyncMock()
        adapter._start_ping = AsyncMock()
        
        result = await adapter.connect()
        
        assert result == True
        assert adapter.is_connected == True
        
        # 检查每个connector的connect都被调用了一次
        for connector_type, connector in adapter.connectors.items():
            connector.connect.assert_called_once()
            logger.info(f"✅ {connector_type.value} connector connect called")
    
    @pytest.mark.asyncio
    async def test_connect_partial_failure(self, adapter):
        """测试部分connector连接失败"""
        connectors = list(adapter.connectors.items())
        
        # 设置前两个connector成功，后两个失败
        for i, (connector_type, connector) in enumerate(connectors):
            if i < 2:  # orderbook和trade成功
                connector.connect = AsyncMock(return_value=True)
            else:  # prices和comments失败
                connector.connect = AsyncMock(return_value=False)
        
        # Mock 其他方法
        adapter._resubscribe_all = AsyncMock()
        adapter._performance_monitor = AsyncMock()
        adapter._start_ping = AsyncMock()
        
        result = await adapter.connect()
        
        assert result == False  # 只要有一个失败，整体就失败
        assert adapter.is_connected == False
        
        # 检查所有connector的connect都被调用了一次
        for connector_type, connector in connectors:
            connector.connect.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_disconnect(self, adapter):
        """测试断开所有connector连接"""
        adapter.is_connected = True
        
        # 设置所有connector的disconnect方法
        for connector in adapter.connectors.values():
            connector.disconnect = AsyncMock()
        
        await adapter.disconnect()
        
        assert adapter.is_connected == False
        
        # 检查每个connector的disconnect都被调用了一次
        for connector_name, connector in adapter.connectors.items():
            connector.disconnect.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_subscribe_valid_market(self, adapter):
        """测试订阅有效的市场 - 适配新的基于asset_id的订阅逻辑"""
        # 1. 准备测试数据
        market_id = "0x1234567890abcdef1234567890abcdef12345678"
        
        # 创建模拟的asset_ids（代币ID） - 一个市场通常有2个代币（Yes/No）
        mock_asset_ids = [
            "asset_id_yes_1234567890abcdef",
            "asset_id_no_1234567890abcdef"
        ]
        
        # 2. Mock缓存方法，让market_id能返回对应的asset_ids
        adapter.get_market_tokens = MagicMock(return_value=mock_asset_ids)
        
        # 3. 设置连接状态和Mock
        adapter.is_connected = True
        subscription_type = SubscriptionType.ORDERBOOK  # 注意：可能需要调整类型名
        
        # 获取对应的connector并mock send_json方法
        target_connector = adapter.connectors[subscription_type]
        target_connector.send_json = AsyncMock()
        target_connector.is_connected = True
        
        # 4. 执行订阅
        await adapter.subscribe([market_id], subscription_type)
        
        # 5. 验证结果
        
        # 5.1 验证get_market_tokens被正确调用
        adapter.get_market_tokens.assert_called_once_with(market_id)
        
        # 5.2 验证subscription_status中包含了正确的asset_ids
        # 注意：现在subscription_status存储的是asset_ids，不是market_ids
        for asset_id in mock_asset_ids:
            assert asset_id in adapter.subscription_status[subscription_type]
        
        # 5.3 验证send_json被调用，且消息格式正确
        target_connector.send_json.assert_called_once()
        call_args = target_connector.send_json.call_args[0][0]
        
        # 验证消息类型
        assert call_args["type"] == "market"
        
        # 验证消息中包含我们的asset_ids
        sent_asset_ids = call_args.get("assets_ids", [])
        for asset_id in mock_asset_ids:
            assert asset_id in sent_asset_ids
        
        # 5.4 验证subscribed_markets
        assert market_id in adapter.subscribed_markets[subscription_type]

    @pytest.mark.asyncio
    async def test_subscribe_market_without_tokens(self, adapter):
        """测试订阅没有代币ID的市场"""
        market_id = "invalid_market_id"
        adapter.is_connected = True
        
        # Mock get_market_tokens返回空列表
        adapter.get_market_tokens = MagicMock(return_value=[])
        
        subscription_type = SubscriptionType.ORDERBOOK
        target_connector = adapter.connectors[subscription_type]
        target_connector.send_json = AsyncMock()
        
        # 执行订阅 - 应该不会发送消息
        await adapter.subscribe([market_id], subscription_type)
        
        # 验证：get_market_tokens被调用
        adapter.get_market_tokens.assert_called_once_with(market_id)
        
        # 验证：send_json没有被调用（因为没有代币ID）
        target_connector.send_json.assert_not_called()
        
        # 验证：subscription_status仍然是空的
        assert len(adapter.subscription_status[subscription_type]) == 0    

    
    @pytest.mark.asyncio
    async def test_subscribe_when_disconnected(self, adapter):
        """测试在未连接状态下订阅"""
        market_id = "0x1234567890abcdef1234567890abcdef12345678"
        adapter.is_connected = False
        
        subscription_type = SubscriptionType.ORDERBOOK
        # 设置connector的send_json方法
        target_connector = adapter.connectors[subscription_type] # 获取将被调用的connector
        target_connector.send_json = AsyncMock() # 只Mock这一个
        target_connector.is_connected = False # 确保连接状态为False
        
        await adapter.subscribe([market_id], subscription_type)
        
        # 不应该发送消息
        target_connector.send_json.assert_not_called()
    
    @pytest.mark.asyncio
    async def test_unsubscribe(self, adapter):
        """测试取消订阅 - 适配新的基于asset_id的订阅逻辑"""
        # 1. 准备测试数据
        market_id = "0x1234567890abcdef1234567890abcdef12345678"
        
        # 创建模拟的asset_ids（代币ID）
        mock_asset_ids = [
            "asset_id_yes_1234567890abcdef",
            "asset_id_no_1234567890abcdef"
        ]
        
        subscription_type = SubscriptionType.ORDERBOOK
        adapter.is_connected = True
        
        # 2. Mock缓存方法，让market_id能返回对应的asset_ids
        adapter.get_market_tokens = MagicMock(return_value=mock_asset_ids)
        
        # 3. 设置初始状态 - 注意：现在subscription_status存储的是asset_id，不是market_id
        # 将asset_ids添加到subscription_status中（模拟已订阅状态）
        adapter.subscription_status[subscription_type].update(mock_asset_ids)
        
        # 将market_id添加到subscribed_markets中
        adapter.subscribed_markets[subscription_type].add(market_id)
        
        # 4. 设置Mock
        target_connector = adapter.connectors[subscription_type]
        target_connector.send_json = AsyncMock()
        target_connector.is_connected = True
        
        # 5. 执行取消订阅
        await adapter.unsubscribe([market_id], subscription_type)
        
        # 6. 验证结果
        
        # 6.1 验证get_market_tokens被正确调用
        adapter.get_market_tokens.assert_called_once_with(market_id)
        
        # 6.2 验证subscription_status中的asset_ids已被移除
        for asset_id in mock_asset_ids:
            assert asset_id not in adapter.subscription_status[subscription_type]
        
        # 6.3 验证subscribed_markets中的market_id已被移除
        assert market_id not in adapter.subscribed_markets[subscription_type]
        
        # 6.4 验证send_json被调用，且消息格式正确
        target_connector.send_json.assert_called_once()
        call_args = target_connector.send_json.call_args[0][0]
        
        # 验证消息类型
        assert call_args["type"] == "unsubscribe"  # 或根据实际协议调整
        
        # 验证消息中包含我们的asset_ids（注意：实际取消订阅消息可能格式不同）
        # 根据你的实际取消订阅消息格式调整以下断言
        sent_asset_ids = call_args.get("assets_ids", [])
        for asset_id in mock_asset_ids:
            assert asset_id in sent_asset_ids
        
        # 6.5 验证日志中没有错误
        # 可以通过检查日志输出或确保没有抛出异常来验证

    @pytest.mark.asyncio
    async def test_unsubscribe_different_types(self, adapter):
        """测试不同类型连接的取消订阅 - 适配新的基于asset_id的逻辑"""
        # 1. 准备测试数据
        market_id = "0x1234567890abcdef1234567890abcdef12345678"
        
        # 模拟不同订阅类型对应的asset_ids
        mock_asset_mapping = {
            SubscriptionType.ORDERBOOK: ["asset_orderbook_yes", "asset_orderbook_no"],
            SubscriptionType.TRADE: ["asset_trade_yes", "asset_trade_no"],
            SubscriptionType.PRICE: [],  # PRICE类型可能不基于asset_ids
            SubscriptionType.COMMENT: [], # COMMENT类型可能不基于asset_ids
        }
        
        # 2. 测试所有订阅类型
        test_cases = [
            (SubscriptionType.ORDERBOOK, {"assets_ids": mock_asset_mapping[SubscriptionType.ORDERBOOK], "type": "unsubscribe"}),
            (SubscriptionType.TRADE, {"assets_ids": mock_asset_mapping[SubscriptionType.TRADE], "type": "unsubscribe"}),
            # PRICE和COMMENT类型可能需要不同的消息格式
            (SubscriptionType.PRICE, {"action": "unsubscribe", "subscriptions": [{"topic": "crypto_prices", "type": "update"}]}),
            (SubscriptionType.COMMENT, {"action": "unsubscribe", "subscriptions": [{"topic": "comments", "type": "comment_created"}]}),
        ]
        
        for subscription_type, expected_msg in test_cases:
            # 重置之前测试的影响
            adapter.subscription_status[subscription_type].clear()
            adapter.subscribed_markets[subscription_type].clear()
                 
            # 3. 对于基于asset_id的订阅类型，Mock转换方法
            if subscription_type in [SubscriptionType.ORDERBOOK, SubscriptionType.TRADE]:
                mock_asset_ids = mock_asset_mapping[subscription_type]
                adapter.get_market_tokens = MagicMock(return_value=mock_asset_ids)
                
                # 设置初始状态：添加asset_ids到subscription_status
                adapter.subscribed_markets[subscription_type].add(market_id)
                adapter.subscription_status[subscription_type].update(mock_asset_ids)
            else:
                # 对于PRICE和COMMENT类型，可能不需要asset_ids转换
                adapter.get_market_tokens = MagicMock(return_value=[])
                
                # 这些类型可能直接订阅，不需要asset_ids
                # 设置其他状态表示已订阅
                mock_topics = expected_msg["subscriptions"][0]["topic"]
                adapter.subscribed_topics[subscription_type].add(mock_topics)
            
            # 4. 设置Mock连接器
            target_connector = adapter.connectors[subscription_type]
            target_connector.send_json = AsyncMock()
            target_connector.is_connected = True
            
            # 5. 执行取消订阅
            if subscription_type in [SubscriptionType.ORDERBOOK, SubscriptionType.TRADE]:
                await adapter.unsubscribe([market_id], subscription_type)
            else:
                await adapter.unsubscribe_rtds(subscription_type)    
            
            # 6. 验证结果
            
            # 6.1 验证get_market_tokens被调用（对于需要转换的类型）
            if subscription_type in [SubscriptionType.ORDERBOOK, SubscriptionType.TRADE]:
                adapter.get_market_tokens.assert_called_once_with(market_id)
                
                # 验证subscription_status中的asset_ids已被移除
                for asset_id in mock_asset_ids:
                    assert asset_id not in adapter.subscription_status[subscription_type]
            
            # 6.2 验证subscribed_markets中的market_id已被移除
            assert market_id not in adapter.subscribed_markets[subscription_type]
            
            # 6.3 验证发送了取消订阅消息
            target_connector.send_json.assert_called_once()
            call_args = target_connector.send_json.call_args[0][0]
            
            # 6.4 验证消息格式正确
            if subscription_type in [SubscriptionType.ORDERBOOK, SubscriptionType.TRADE]:
                # CLOB端点格式
                assert call_args["type"] == "unsubscribe"
                
                # 验证消息中包含我们的asset_ids
                sent_asset_ids = call_args.get("assets_ids", [])
                for asset_id in mock_asset_ids:
                    assert asset_id in sent_asset_ids
            else:
                # RTDS端点格式
                assert call_args["action"] == "unsubscribe"
                # 可以根据需要进一步验证subscriptions内容
            
            # 7. 清理，准备下一个测试用例
            target_connector.send_json.reset_mock()
    
    def test_handle_orderbook_update(self, adapter, sample_orderbook_message):
        """测试处理订单簿更新"""
        asset_id = sample_orderbook_message["asset_id"]
        
        # 模拟回调
        callback_mock = Mock()
        adapter.add_callback(callback_mock)

        receive_timestamp_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        
        # 处理订单簿消息
        adapter._handle_orderbook(sample_orderbook_message, receive_timestamp_ms)
        
        # 检查订单簿状态更新
        assert asset_id in adapter.orderbook_snapshots
        
        orderbook = adapter.orderbook_snapshots[asset_id]
        assert len(orderbook.bids) == 2
        assert len(orderbook.asks) == 2
        assert orderbook.bids[0].price == Decimal("0.65")
        assert orderbook.bids[0].quantity == Decimal("1000")
        assert orderbook.server_timestamp == int(sample_orderbook_message["timestamp"])
        assert orderbook.receive_timestamp == receive_timestamp_ms
        
        # 检查回调被调用
        callback_mock.assert_called_once()
    
    def test_handle_trade_update(self, adapter):
        """测试处理交易消息"""
        # 模拟回调
        callback_mock = Mock()
        adapter.add_callback(callback_mock)

        # 创建一个完整的 Trade 消息
        trade_message = {
            "event_type": "trade",
            "asset_id": "test-asset-1",
            "id": "trade-123",
            "last_update": "1234567890123",
            "maker_orders": [
                {
                    "asset_id": "test-asset-1",
                    "matched_amount": "50",
                    "order_id": "maker-order-1",
                    "outcome": "YES",
                    "owner": "maker-address",
                    "price": "0.65"
                },
                {
                    "asset_id": "test-asset-1",
                    "matched_amount": "50",
                    "order_id": "maker-order-2",
                    "outcome": "YES",
                    "owner": "maker-address-2",
                    "price": "0.65"
                }
            ],
            "market": "0x1234567890abcdef1234567890abcdef12345678",
            "matchtime": "1234567890000",
            "outcome": "YES",
            "owner": "taker-address",
            "price": "0.65",
            "side": "BUY",
            "size": "100",
            "status": "MATCHED",
            "taker_order_id": "taker-order-123",
            "timestamp": "1234567890123",
            "trade_owner": "taker-address",
            "type": "TRADE"
        }

        # 确保市场在订阅列表中
        asset_id = trade_message["asset_id"]
        adapter.subscribed_markets[SubscriptionType.TRADE].add(asset_id)

        # 处理交易消息
        adapter._handle_trade(trade_message)

        # 检查回调被调用
        callback_mock.assert_called_once()
        
        # 检查回调参数
        market_data = callback_mock.call_args[0][0]
        assert isinstance(market_data, MarketData)
        assert market_data.symbol == trade_message["asset_id"]
        assert market_data.last_price == Decimal("0.65")
        
        # 检查交易数据 - 注意这里检查的是TradePrice对象
        assert market_data.last_trade is not None
        assert market_data.last_trade.price == Decimal("0.65")
        assert market_data.last_trade.size == Decimal("100")
        assert market_data.last_trade.side == "buy"  # 小写
        
        # 检查交易历史被更新
        assert trade_message["asset_id"] in adapter.trade_history
        assert len(adapter.trade_history[trade_message["asset_id"]]) == 1
        
        trade = adapter.trade_history[trade_message["asset_id"]][0]
        assert trade.id == "trade-123"
        assert trade.price == Decimal("0.65")
        assert trade.size == Decimal("100")
        assert trade.side == "BUY"
        assert trade.status == "MATCHED"
        assert len(trade.maker_orders) == 2
        
        # 检查最后成交价被更新
        assert trade_message["asset_id"] in adapter.last_trade_prices
        trade_price = adapter.last_trade_prices[trade_message["asset_id"]]
        assert trade_price.price == Decimal("0.65")
        assert trade_price.size == Decimal("100")
    
    def test_handle_price_change_update(self, adapter, sample_price_change_message):
        """测试处理价格变动更新"""
        # 模拟回调
        callback_mock = Mock()
        adapter.add_callback(callback_mock)

        # 处理价格变动消息
        receive_timestamp_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        adapter._handle_price_change(sample_price_change_message, receive_timestamp_ms)
        
        # 检查回调被调用
        assert callback_mock.call_count == 2
        
        # 检查回调参数
        market_data = callback_mock.call_args[0][0]
        assert isinstance(market_data, MarketData)
        assert market_data.exchange == ExchangeType.POLYMARKET
        
        # 价格变动消息应该包含特定信息
        assert market_data.symbol == sample_price_change_message.get("price_changes")[1]["asset_id"]
    
    def test_handle_raw_message_array(self, adapter, sample_orderbook_message, 
                                                        sample_trade_message, sample_price_change_message):
        """测试处理包含不同类型消息的数组格式"""
        # 创建一个包含不同类型消息的数组
        array_message = [
            sample_orderbook_message,  # 订单簿消息
            sample_trade_message,      # 交易消息
            sample_price_change_message,  # 价格变化消息
            sample_orderbook_message,  # 再一个订单簿消息
        ]
        
        # Mock 所有可能的处理方法
        with patch.object(adapter, '_handle_orderbook') as mock_handle_orderbook, \
            patch.object(adapter, '_handle_trade') as mock_handle_trade, \
            patch.object(adapter, '_handle_price_change') as mock_handle_price_change:
            
            # 执行原始方法
            adapter._handle_raw_message(array_message)
            
            # 验证每个处理方法被调用的次数和参数
            # 两个订单簿消息
            assert mock_handle_orderbook.call_count == 2
            assert mock_handle_trade.call_count == 1
            assert mock_handle_price_change.call_count == 1
            
            # 验证参数是否正确传递
            # 订单簿调用
            orderbook_calls = mock_handle_orderbook.call_args_list
            assert orderbook_calls[0].args[0] == sample_orderbook_message
            assert orderbook_calls[1].args[0] == sample_orderbook_message
            
            # 交易调用
            trade_calls = mock_handle_trade.call_args_list
            assert trade_calls[0].args[0] == sample_trade_message
            
            # 价格变化调用
            price_change_calls = mock_handle_price_change.call_args_list
            assert price_change_calls[0].args[0] == sample_price_change_message
    
    def test_handle_raw_message_book(self, adapter, sample_orderbook_message):
        """测试处理订单簿原始消息"""
        with patch.object(adapter, '_handle_orderbook') as mock_handler:
            adapter._handle_raw_message(sample_orderbook_message)
            
            # 检查方法被调用，包含消息和时间戳两个参数
            mock_handler.assert_called_once()
            
            # 获取调用参数
            args = mock_handler.call_args[0]
            
            # 应该有两个参数
            assert len(args) == 2
            # 第一个参数是消息数据
            assert args[0] == sample_orderbook_message
            # 第二个参数是整数时间戳
            assert isinstance(args[1], int)
            # 时间戳应该是一个合理的值（当前时间附近的毫秒时间戳）
            current_timestamp = int(datetime.now(timezone.utc).timestamp() * 1000)
            # 时间戳应该在合理范围内（比如最近10秒内）
            assert abs(args[1] - current_timestamp) < 10000  # 10秒内
    
    def test_handle_raw_message_trade(self, adapter, sample_trade_message):
        """测试处理交易原始消息"""
        with patch.object(adapter, '_handle_trade') as mock_handler:
            adapter._handle_raw_message(sample_trade_message)
            mock_handler.assert_called_once_with(sample_trade_message)
    
    def test_handle_raw_message_price_change(self, adapter, sample_price_change_message):
        """测试处理价格变动原始消息"""
        with patch.object(adapter, '_handle_price_change') as mock_handler:
            adapter._handle_raw_message(sample_price_change_message)
            mock_handler.assert_called_once()

            # 获取调用参数
            args = mock_handler.call_args[0]
            
            # 应该有两个参数
            assert len(args) == 2
            # 第一个参数是消息数据
            assert args[0] == sample_price_change_message
            # 第二个参数是整数时间戳
            assert isinstance(args[1], int)
            # 时间戳应该是一个合理的值（当前时间附近的毫秒时间戳）
            current_timestamp = int(datetime.now(timezone.utc).timestamp() * 1000)
            # 时间戳应该在合理范围内（比如最近10秒内）
            assert abs(args[1] - current_timestamp) < 10000  # 10秒内
    
    def test_handle_raw_message_unknown_type(self, adapter):
        """测试处理未知类型的消息"""
        unknown_message = {
            "market": "0x123",
            "event_type": "unknown_type",
            "data": "test"
        }
    
        # 这个应该记录警告但不抛出异常
        adapter._handle_raw_message(unknown_message)
    
    def test_handle_heartbeat(self, adapter):
        """测试处理心跳消息"""
        # 心跳消息不应该抛出异常
        adapter._handle_heartbeat({"event_type": "heartbeat"})
    
    def test_handle_error(self, adapter):
        """测试处理错误消息"""
        error_message = {"event_type": "error", "message": "Test error"}
        
        # 错误消息应该被记录但不抛出异常
        adapter._handle_error(error_message)
    
    def test_create_market_data(self, adapter):
        """测试从订单簿创建市场数据"""
        market_id = "0x1234567890abcdef1234567890abcdef12345678"
        
        # 获取当前时间的毫秒时间戳
        now = datetime.now(timezone.utc)
        now_timestamp_ms = int(now.timestamp() * 1000)
        
        # 创建模拟订单簿，使用正确的时间戳参数
        mock_orderbook = OrderBook(
            bids=[OrderBookLevel(price=Decimal("0.65"), quantity=Decimal("1000"))],
            asks=[OrderBookLevel(price=Decimal("0.66"), quantity=Decimal("800"))],
            server_timestamp=now_timestamp_ms,  # 服务器时间戳
            receive_timestamp=now_timestamp_ms,  # 接收时间戳
            symbol=market_id
        )
        
        # 将订单簿设置到适配器中
        adapter.orderbook_snapshots[market_id] = mock_orderbook
        
        # 测试创建市场数据
        market_data = adapter._create_market_data(symbol=market_id, exchange=ExchangeType.POLYMARKET, orderbook=mock_orderbook)
        
        # 验证结果
        assert market_data is not None
        assert market_data.symbol == market_id
        assert market_data.exchange == ExchangeType.POLYMARKET
        assert market_data.market_type == MarketType.PREDICTION
        assert market_data.orderbook == mock_orderbook
    
    def test_create_market_data_nonexistent(self, adapter):
        """测试为不存在的市场创建市场数据"""
        market_data = adapter._create_market_data(symbol="nonexistent_market", exchange=ExchangeType.POLYMARKET)
        
        assert market_data is None
    
    def test_normalize_data_websocket_version(self, adapter):
        """测试 WebSocket 版本的数据标准化"""
        # WebSocket 版本中 normalize_data 应该返回 None
        result = adapter.normalize_data({"some": "data"})
        assert result is None
    
    def test_get_connection_status(self, adapter):
        """测试获取连接状态 - 多connector版本"""
        # 设置不同的连接状态
        adapter.is_connected = True
        
        # 创建不同的市场ID
        market1 = "0x1234567890abcdef1234567890abcdef12345678"
        market2 = "0x876543210fedcba09876543210fedcba09876543"
        market3 = "0xabcdef1234567890abcdef1234567890abcdef12"
        
        # 获取连接器类型列表
        connector_types = list(adapter.subscription_status.keys())
        
        if len(connector_types) >= 3:
            # 为不同连接器设置不同的订阅
            adapter.subscription_status[connector_types[0]].add(market1)
            adapter.subscription_status[connector_types[0]].add(market2)
            adapter.subscription_status[connector_types[1]].add(market1)
            adapter.subscription_status[connector_types[2]].add(market3)
        
        # 设置连接器状态
        for i, (connector_type, connector) in enumerate(adapter.connectors.items()):
            # 让一个连接器断开连接，测试全局状态
            connector.is_connected = (i < 2)  # 前两个连接，第三个断开
        
        adapter.message_count = 150
        
        # 设置每个connector的连接信息
        for connector in adapter.connectors.values():
            connector.get_connection_info.return_value = {"status": "connected", "url": "wss://test.com"}
        
        status = adapter.get_connection_status()
        
        # 验证基础状态
        assert status["name"] == "polymarket"
        assert status["exchange"] == "polymarket"
        
        # 验证全局连接状态（所有连接器都连接才算真正连接）
        expected_global_connected = all(connector.is_connected for connector in adapter.connectors.values())
        assert status["is_connected"] == expected_global_connected
        
        # 验证所有订阅的市场都被汇总
        all_subscribed = set()
        for markets in adapter.subscription_status.values():
            all_subscribed.update(markets)
        
        for market in all_subscribed:
            assert market in status["subscribed_markets"]
        
        # 验证连接详情
        assert "connection_details" in status
        
        # 验证每个连接器的详情
        for connector_type, connector in adapter.connectors.items():
            connector_str = connector_type.value
            assert connector_str in status["connection_details"]
            detail = status["connection_details"][connector_str]
            
            assert detail["is_connected"] == connector.is_connected
            # 验证订阅的市场列表正确
            expected_markets = list(adapter.subscription_status[connector_type])
            assert set(detail["subscribed_markets"]) == set(expected_markets)
    
    @pytest.mark.asyncio
    async def test_get_market_list_success(self, adapter):
        """测试成功获取市场列表"""
        expected_markets = [
            {"id": "0x123", "question": "Market 1"},
            {"id": "0x456", "question": "Market 2"}
        ]
        
        # 创建模拟的 RESTConnector
        mock_connector = AsyncMock()
        
        # 创建模拟的响应对象
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json.return_value = expected_markets
        
        # 设置 connector.get() 返回模拟的响应
        mock_connector.get.return_value = mock_response
        
        # Mock RESTConnector 类的实例化
        with patch('market.adapter.polymarket_adapter.RESTConnector') as MockRESTConnector:
            # 设置异步上下文管理器
            MockRESTConnector.return_value.__aenter__.return_value = mock_connector
            MockRESTConnector.return_value.__aexit__.return_value = None
            
            result = await adapter.get_market_list(limit=10)
            
            assert result == expected_markets
            
            # 验证 RESTConnector 被正确调用
            MockRESTConnector.assert_called_once_with(
                base_url=adapter.rest_urls[0],
                timeout=10,
                name="polymarket_rest"
            )
            
            # 验证 get 方法被正确调用
            mock_connector.get.assert_called_once_with(
                "/markets",
                params={
                    "limit": 10,
                    "closed": "false",
                    "order": "volumeNum",
                    "ascending": "false",
                }
            )
    
    @pytest.mark.asyncio 
    async def test_get_market_list_failure(self, adapter):
        """测试获取市场列表失败"""
        with patch('aiohttp.ClientSession.get') as mock_get:
            mock_response = AsyncMock()
            mock_response.status = 500
            mock_get.return_value.__aenter__.return_value = mock_response
            
            result = await adapter.get_market_list(10)
            
            assert result == []
    
    @pytest.mark.asyncio
    async def test_attempt_reconnect(self, adapter):
        """测试重连逻辑"""
        # 获取连接器类型并设置 subscription_status
        # 假设至少有一个连接器类型
        connector_types = list(adapter.subscription_status.keys())
        if not connector_types:
            pytest.skip("No connector types available in adapter")
        
        # 为每个连接器类型添加订阅的市场
        test_market = "0x123"
        for connector_type in connector_types:
            adapter.subscription_status[connector_type].add(test_market)

        with patch.object(adapter, 'connect', new_callable=AsyncMock) as mock_connect, \
            patch.object(adapter, '_do_subscribe', new_callable=AsyncMock) as mock_subscribe:

            mock_connect.return_value = True

            await adapter._attempt_reconnect()

            mock_connect.assert_called_once()
            
            # _do_subscribe 应该为每个连接器类型被调用一次
            # 检查调用次数
            expected_call_count = len(connector_types)
            assert mock_subscribe.call_count == expected_call_count
            
            # 检查每次调用的参数
            expected_calls = []
            for connector_type in connector_types:
                # 注意：_do_subscribe 应该被调用，参数为 (market_list, subscription_type)
                expected_calls.append(call([test_market], connector_type))
            
            # 使用 assert_has_calls 而不是 assert_called_once_with
            mock_subscribe.assert_has_calls(expected_calls, any_order=True)
    
    def test_handle_connection_error(self, adapter):
        """测试连接错误处理"""
        adapter.is_connected = True

        # 创建模拟的已完成任务
        mock_task = AsyncMock()
        
        # 模拟 asyncio.create_task 来避免 "no running event loop" 错误
        with patch('asyncio.create_task') as mock_create_task:
            mock_create_task.return_value = mock_task
            
            adapter._handle_connection_error("orderbook", Exception("Connection lost"))
            
            # 断言连接状态被设置为 False
            assert adapter.is_connected == False
            
            # 断言创建了重连任务
            mock_create_task.assert_called_once()
            
            # 验证调用了 _attempt_reconnect
            task_args = mock_create_task.call_args[0]
            # task_args[0] 应该是 _attempt_reconnect() 的调用结果
            assert task_args is not None
    
    def test_update_orderbook(self, adapter):
        """测试更新订单簿方法"""
        market_id = "0x1234567890abcdef1234567890abcdef12345678"
        bids = [{"price": "0.65", "size": "1000"}, {"price": "0.64", "size": "500"}]
        asks = [{"price": "0.66", "size": "800"}, {"price": "0.67", "size": "1200"}]
        receive_timestamp_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        server_timestamp = receive_timestamp_ms - 1000
        
        adapter._update_orderbook(market_id, bids, asks, server_timestamp, receive_timestamp_ms)
        
        # 检查订单簿被更新
        assert market_id in adapter.orderbook_snapshots
        assert adapter.orderbook_snapshots[market_id].server_timestamp == server_timestamp
        assert adapter.orderbook_snapshots[market_id].receive_timestamp == receive_timestamp_ms
        
        orderbook = adapter.orderbook_snapshots[market_id]
        assert len(orderbook.bids) == 2
        assert len(orderbook.asks) == 2
    
    def test_update_market_best_prices(self, adapter):
        """测试更新市场最优报价"""
        market_id = "0x123"
        asset_id = "test_asset"
        best_bid = "0.002"
        best_ask = "0.003"
        
        # 这个方法应该不会抛出异常
        adapter._update_market_best_prices(market_id, asset_id, best_bid, best_ask)
        
        # 检查是否有任何状态更新（根据实现）
        # 这里只是确保方法可以正常调用

if __name__ == "__main__":
    # 运行测试
    pytest.main([__file__, "-v"])