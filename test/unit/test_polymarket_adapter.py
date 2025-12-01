import pytest
import asyncio
import logging
from unittest.mock import Mock, patch, AsyncMock, MagicMock
from decimal import Decimal
from datetime import datetime, timezone
import sys
import os

# 添加 src 目录到 Python 路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from market.adapter.polymarket_adapter import PolymarketAdapter
from market.core.data_models import MarketData, OrderBook, OrderBookLevel, ExchangeType, MarketType

# 配置测试日志
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

class TestPolymarketWebSocketAdapter:
    """PolymarketAdapter 单元测试"""
    
    @pytest.fixture
    def adapter(self):
        """创建适配器实例"""
        # Mock WebSocketConnector 以避免初始化错误
        with patch('market.adapter.polymarket_adapter.WebSocketConnector') as mock_ws:
            mock_connector = MagicMock()
            mock_ws.return_value = mock_connector
            adapter = PolymarketAdapter()
            adapter.connector = mock_connector  # 确保使用mock的connector
            return adapter
    
    @pytest.fixture
    def sample_orderbook_message(self):
        """提供样本订单簿消息"""
        return {
            "type": "orderbook",
            "market": "0x1234567890abcdef1234567890abcdef12345678",
            "sequence": 1001,
            "bids": [["0.65", "1000"], ["0.64", "500"]],
            "asks": [["0.66", "800"], ["0.67", "1200"]]
        }
    
    @pytest.fixture
    def sample_trade_message(self):
        """提供样本交易消息"""
        return {
            "type": "trade",
            "market": "0x1234567890abcdef1234567890abcdef12345678",
            "price": "0.65",
            "quantity": "100",  # 注意：字段名是 quantity 而不是 last_quantity
            "side": "buy",
            "timestamp": 1640995200000  # 2022-01-01 00:00:00 UTC
        }
    
    def test_initialization(self, adapter):
        """测试适配器初始化"""
        assert adapter.name == "polymarket"
        assert adapter.exchange_type == ExchangeType.POLYMARKET
        assert adapter.is_connected == False
        assert len(adapter.callbacks) == 0
        assert len(adapter.subscribed_symbols) == 0
        
        # WebSocket 版本特有的属性
        assert "wss://clob.polymarket.com/ws" in adapter.ws_urls
        assert adapter.message_count == 0
        assert adapter.performance_stats["messages_per_second"] == 0
        assert adapter._connection_established == False
    
    @pytest.mark.asyncio
    async def test_connect_success(self, adapter):
        """测试成功连接 WebSocket"""
        adapter.connector.connect = AsyncMock(return_value=True)
        
        result = await adapter.connect()
        
        assert result == True
        assert adapter.is_connected == True
        assert adapter._connection_established == True
        adapter.connector.connect.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_connect_failure(self, adapter):
        """测试 WebSocket 连接失败"""
        adapter.connector.connect = AsyncMock(return_value=False)
        
        result = await adapter.connect()
        
        assert result == False
        assert adapter.is_connected == False
        assert adapter._connection_established == False
    
    @pytest.mark.asyncio
    async def test_disconnect(self, adapter):
        """测试断开连接"""
        adapter.is_connected = True
        adapter._connection_established = True
        
        adapter.connector.disconnect = AsyncMock()
        await adapter.disconnect()
        
        assert adapter.is_connected == False
        assert adapter._connection_established == False
        adapter.connector.disconnect.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_subscribe_valid_market(self, adapter):
        """测试订阅有效的市场 - WebSocket 版本"""
        market_id = "0x1234567890abcdef1234567890abcdef12345678"
        adapter.is_connected = True
        adapter._connection_established = True
        
        adapter.connector.send_json = AsyncMock()
        await adapter._do_subscribe([market_id])
        
        # 修复：检查订阅状态 - 确保市场ID被添加到订阅集合
        assert market_id in adapter.subscribed_symbols
        
        # 检查是否发送了订阅消息
        adapter.connector.send_json.assert_called_once()
        call_args = adapter.connector.send_json.call_args[0][0]
        assert call_args["type"] == "subscribe"
        assert market_id in call_args["markets"]
    
    @pytest.mark.asyncio
    async def test_subscribe_when_disconnected(self, adapter):
        """测试在未连接状态下订阅"""
        market_id = "0x1234567890abcdef1234567890abcdef12345678"
        adapter.is_connected = False
        
        adapter.connector.send_json = AsyncMock()
        await adapter._do_subscribe([market_id])
        
        # 不应该发送消息
        adapter.connector.send_json.assert_not_called()
    
    @pytest.mark.asyncio
    async def test_unsubscribe(self, adapter):
        """测试取消订阅 - WebSocket 版本"""
        market_id = "0x1234567890abcdef1234567890abcdef12345678"
        adapter.is_connected = True
        adapter.subscribed_symbols.add(market_id)
        adapter.orderbook_snapshots[market_id] = Mock()
        adapter.last_sequence_nums[market_id] = 1000
        
        adapter.connector.send_json = AsyncMock()
        await adapter._do_unsubscribe([market_id])
        
        # 修复：检查取消订阅状态 - 确保市场ID从订阅集合中移除
        assert market_id not in adapter.subscribed_symbols
        
        # 检查是否发送了取消订阅消息
        adapter.connector.send_json.assert_called_once()
        call_args = adapter.connector.send_json.call_args[0][0]
        assert call_args["type"] == "unsubscribe"
        assert market_id in call_args["markets"]
    
    def test_handle_orderbook_update(self, adapter, sample_orderbook_message):
        """测试处理订单簿更新"""
        market_id = sample_orderbook_message["market"]
        
        # 模拟回调
        callback_mock = Mock()
        adapter.add_callback(callback_mock)
        
        # 处理订单簿消息
        adapter._handle_orderbook_update(sample_orderbook_message)
        
        # 检查订单簿状态更新
        assert market_id in adapter.orderbook_snapshots
        assert adapter.last_sequence_nums[market_id] == 1001
        
        orderbook = adapter.orderbook_snapshots[market_id]
        assert len(orderbook.bids) == 2
        assert len(orderbook.asks) == 2
        assert orderbook.bids[0].price == Decimal("0.65")
        assert orderbook.bids[0].quantity == Decimal("1000")
        
        # 检查回调被调用
        callback_mock.assert_called_once()
    
    def test_handle_orderbook_update_sequence_gap(self, adapter, sample_orderbook_message):
        """测试处理序列号跳跃的订单簿更新"""
        market_id = sample_orderbook_message["market"]
        adapter.last_sequence_nums[market_id] = 500  # 设置一个很旧的序列号
        
        # 处理订单簿消息（序列号从500跳到1001）
        adapter._handle_orderbook_update(sample_orderbook_message)
        
        # 应该仍然处理更新，但记录警告
        assert adapter.last_sequence_nums[market_id] == 1001
    
    def test_handle_orderbook_update_old_sequence(self, adapter, sample_orderbook_message):
        """测试处理旧的序列号"""
        market_id = sample_orderbook_message["market"]
        adapter.last_sequence_nums[market_id] = 2000  # 比消息序列号新
        
        # 处理订单簿消息
        adapter._handle_orderbook_update(sample_orderbook_message)
        
        # 不应该更新序列号
        assert adapter.last_sequence_nums[market_id] == 2000
    
    def test_handle_trade_update(self, adapter, sample_trade_message):
        """测试处理交易更新"""
        # 模拟回调
        callback_mock = Mock()
        adapter.add_callback(callback_mock)

        # 修复：确保市场在订阅列表中，否则交易更新会被忽略
        market_id = sample_trade_message["market"]
        adapter.subscribed_symbols.add(market_id)

        # 处理交易消息
        adapter._handle_trade_update(sample_trade_message)

        # 检查回调被调用
        callback_mock.assert_called_once()
        
        # 检查回调参数
        market_data = callback_mock.call_args[0][0]
        assert isinstance(market_data, MarketData)
        assert market_data.symbol == sample_trade_message["market"]
        assert market_data.last_price == Decimal("0.65")
        
        # 检查交易数据
        assert market_data.last_trade is not None
        assert market_data.last_trade.price == Decimal("0.65")
        assert market_data.last_trade.quantity == Decimal("100")
        assert market_data.last_trade.is_buyer_maker == False  # 因为 side 是 'buy'
    
    def test_handle_raw_message_performance_tracking(self, adapter, sample_orderbook_message):
        """测试原始消息处理的性能跟踪"""
        initial_count = adapter.message_count
        
        adapter._handle_raw_message(sample_orderbook_message)
        
        # 检查消息计数增加
        assert adapter.message_count == initial_count + 1
        assert adapter.last_message_time is not None
    
    def test_handle_heartbeat(self, adapter):
        """测试处理心跳消息"""
        # 心跳消息不应该抛出异常
        adapter._handle_heartbeat({"type": "heartbeat"})
    
    def test_handle_error(self, adapter):
        """测试处理错误消息"""
        error_message = {"type": "error", "message": "Test error"}
        
        # 错误消息应该被记录但不抛出异常
        adapter._handle_error(error_message)
    
    def test_create_market_data(self, adapter):
        """测试从订单簿创建市场数据"""
        market_id = "0x1234567890abcdef1234567890abcdef12345678"
        
        # 创建模拟订单簿
        mock_orderbook = OrderBook(
            bids=[OrderBookLevel(price=Decimal("0.65"), quantity=Decimal("1000"))],
            asks=[OrderBookLevel(price=Decimal("0.66"), quantity=Decimal("800"))],
            timestamp=datetime.now(timezone.utc),
            symbol=market_id
        )
        adapter.orderbook_snapshots[market_id] = mock_orderbook
        
        market_data = adapter._create_market_data(market_id)
        
        assert market_data is not None
        assert market_data.symbol == market_id
        assert market_data.exchange == ExchangeType.POLYMARKET
        assert market_data.market_type == MarketType.PREDICTION
        assert market_data.orderbook == mock_orderbook
    
    def test_create_market_data_nonexistent(self, adapter):
        """测试为不存在的市场创建市场数据"""
        market_data = adapter._create_market_data("nonexistent_market")
        
        assert market_data is None
    
    def test_normalize_data_websocket_version(self, adapter):
        """测试 WebSocket 版本的数据标准化"""
        # WebSocket 版本中 normalize_data 应该返回 None
        result = adapter.normalize_data({"some": "data"})
        assert result is None
    
    def test_get_connection_status(self, adapter):
        """测试获取连接状态 - WebSocket 版本"""
        adapter.is_connected = True
        adapter._connection_established = True
        adapter.subscribed_symbols.add("0x123")
        adapter.message_count = 150
        
        # Mock connector 的 get_connection_info 方法
        adapter.connector.get_connection_info.return_value = {"status": "connected"}
        
        status = adapter.get_connection_status()
        
        assert status["name"] == "polymarket"
        assert status["exchange"] == "polymarket"
        assert status["is_connected"] == True
        assert status["connection_established"] == True
        assert "0x123" in status["subscribed_symbols"]
        assert "performance" in status
        assert "websocket_info" in status
    
    @pytest.mark.asyncio
    async def test_get_market_list_success(self, adapter):
        """测试成功获取市场列表"""
        expected_markets = [
            {"id": "0x123", "question": "Market 1"},
            {"id": "0x456", "question": "Market 2"}
        ]
        
        with patch('aiohttp.ClientSession.get') as mock_get:
            mock_response = AsyncMock()
            mock_response.status = 200
            mock_response.json.return_value = expected_markets
            mock_get.return_value.__aenter__.return_value = mock_response
            
            result = await adapter.get_market_list(10)
            
            assert result == expected_markets
            mock_get.assert_called_once()
    
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
        adapter.subscribed_symbols.add("0x123")
        
        with patch.object(adapter, 'connect', new_callable=AsyncMock) as mock_connect, \
             patch.object(adapter, '_do_subscribe', new_callable=AsyncMock) as mock_subscribe:
            
            mock_connect.return_value = True
            
            await adapter._attempt_reconnect()
            
            mock_connect.assert_called_once()
            mock_subscribe.assert_called_once_with(["0x123"])
    
    @pytest.mark.asyncio
    async def test_performance_monitor(self, adapter):
        """测试性能监控"""
        adapter.is_connected = True
        adapter.message_count = 50
        
        # 运行性能监控一小段时间
        monitor_task = asyncio.create_task(adapter._performance_monitor())
        await asyncio.sleep(0.1)
        monitor_task.cancel()
        
        try:
            await monitor_task
        except asyncio.CancelledError:
            pass
        
        # 性能统计应该被更新
        assert adapter.performance_stats["last_update"] is not None
    
    def test_handle_connection_error(self, adapter):
        """测试连接错误处理"""
        adapter.is_connected = True
        adapter._connection_established = True
        
        # 修复：模拟 asyncio.create_task 来避免 "no running event loop" 错误
        with patch('asyncio.create_task') as mock_create_task:
            adapter._handle_connection_error(Exception("Test error"))
            
            # 检查连接状态被重置
            assert adapter.is_connected == False
            assert adapter._connection_established == False
            
            # 检查是否尝试创建重连任务
            mock_create_task.assert_called_once()