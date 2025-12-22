import asyncio
import logging
import sys
import os
import aiohttp
import json
from decimal import Decimal
from datetime import datetime, timezone
from typing import List

# 添加 src 目录到 Python 路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from market.service.rest_connector import RESTConnector
from market import PolymarketAdapter, WebSocketManager, MarketRouter, MarketData, OrderBook
from market.adapter.polymarket_adapter import SubscriptionType

# 配置详细日志
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

async def debug_gamma_api():
    """调试 Gamma API 的实际响应"""
    adapter = PolymarketAdapter()
    
    print("=== 调试 Gamma API 响应 ===")
    
    try:
        async with RESTConnector(
            base_url=adapter.rest_urls[0],
            timeout=10,
            name="polymarket_debug"
        ) as connector:
            
            # 测试不同的参数组合
            test_params = [
                {"limit": 5},
                {"limit": 5, "closed": "false"},
                {"limit": 5, "closed": "true"},
                {"limit": 5, "order": "volumeNum", "ascending": "false"},
            ]
            
            for i, params in enumerate(test_params):
                print(f"\n--- 测试参数组合 {i+1}: {params} ---")
                
                response = await connector.get("/markets", params=params)
                
                if response.status == 200:
                    markets = await response.json()
                    active_count = sum(1 for m in markets if m.get('closed') is False)
                    
                    print(f"返回 {len(markets)} 个市场，其中 {active_count} 个活跃")
                    
                    for market in markets[:2]:
                        print(f"  市场: {market.get('id')} - {market.get('question', '')[:50]}")
                        print(f"    状态: closed={market.get('closed')}, active={market.get('active')}")
                        print(f"    结束时间: {market.get('endDate')}")
                        print(f"    交易量: {market.get('volumeNum')}")
                else:
                    error_text = await response.text()
                    print(f"请求失败: HTTP {response.status} - {error_text}")
                    
    except Exception as e:
        print(f"调试过程中出错: {e}")

async def debug_polymarket_subscription():
    """直接测试真实的 PolymarketAdapter 订阅功能"""
    print("=== 测试真实 PolymarketAdapter 订阅功能 ===")
    
    adapter = PolymarketAdapter()
    
    # 获取市场列表，特别关注活跃且未关闭的市场
    print("\n1. 获取市场列表...")
    try:
        # 尝试获取更多市场，寻找活跃的
        markets = await adapter.get_active_market(limit=50)
        if markets:
            # 寻找真正活跃且未关闭的市场
            active_markets = []
            for market in markets:
                # 检查多个活跃指标
                is_active = (
                    market.get('active') is True and 
                    market.get('closed') is False and
                    market.get('acceptingOrders') is True and
                    market.get('volume24hr', 0) > 0  # 24小时内有交易量
                )
                
                if is_active and market.get('clobTokenIds'):
                    active_markets.append(market)
                    if len(active_markets) >= 2:
                        break
            
            if active_markets:
                print("找到活跃市场:")
                for market in active_markets:
                    print(f"  市场 {market['id']}: {market['question'][:50]}...")
                    print(f"    状态: active={market.get('active')}, closed={market.get('closed')}, fpmmLive={market.get('fpmmLive')}")
                    print(f"    交易量: 24h={market.get('volume24hr', 0)}")
                
                # 使用这些市场的token ID
                market_tokens = []
                for market in active_markets:
                    try:
                        token_ids = json.loads(market['clobTokenIds'])
                        if token_ids:
                            market_tokens.append(token_ids[0])
                    except:
                        pass
                
                if market_tokens:
                    market_ids = market_tokens
                    print(f"✅ 使用活跃市场的 Token IDs: {market_ids}")
                else:
                    # 如果找不到活跃市场，尝试使用官方示例的token ID
                    market_ids = ["109681959945973300464568698402968596289258214226684818748321941747028805721376"]
                    print(f"⚠️ 使用官方示例 Token ID: {market_ids}")
            else:
                print("⚠️ 未找到活跃市场，使用官方示例token ID")
                market_ids = ["109681959945973300464568698402968596289258214226684818748321941747028805721376"]
        else:
            market_ids = ["109681959945973300464568698402968596289258214226684818748321941747028805721376"]
    except Exception as e:
        print(f"❌ 获取市场列表失败: {e}")
        market_ids = ["109681959945973300464568698402968596289258214226684818748321941747028805721376"]
    
    # 测试 WebSocket 连接和订阅
    print("\n2. 测试 WebSocket 连接和订阅...")
    await test_real_polymarket_adapter(adapter, market_ids)

async def test_real_polymarket_adapter(adapter, market_ids):
    """测试真实的 PolymarketAdapter"""
    print("=== 测试真实 PolymarketAdapter ===")
    
    ws_manager = WebSocketManager()
    market_router = MarketRouter()
    
    ws_manager.register_adapter('polymarket', adapter)
    market_router.register_adapter('polymarket', adapter)
    
    received_data = []
    
    def on_market_data(data: MarketData):
        print(f"🎉 收到市场数据: {data.symbol}")
        if data.orderbook:
            bids_count = len(data.orderbook.bids)
            asks_count = len(data.orderbook.asks)
            print(f"   订单簿: {bids_count} bids, {asks_count} asks")
            if data.orderbook.bids and data.orderbook.asks:
                spread = data.orderbook.get_spread()
                print(f"   点差: {spread}")
        if data.last_price:
            print(f"   最新价格: {data.last_price}")
        if data.last_trade:
            print(f"   最新交易: {data.last_trade.quantity} @ {data.last_trade.price}")
        received_data.append(data)
    
    market_router.add_callback(on_market_data)
    
    try:
        print("启动 WebSocket 连接...")
        await ws_manager.start()
        
        # 等待连接建立
        print("等待连接建立...")
        await asyncio.sleep(5)
        
        # 获取连接状态
        ws_status = ws_manager.get_connection_status()
        adapter_status = adapter.get_connection_status()
        
        print(f"WebSocketManager 连接状态: {ws_status}")
        print(f"适配器连接状态: {adapter_status}")
        
        # 正确检查连接状态
        is_connected = ws_status.get('polymarket', False)
        
        if is_connected:
            print("✅ WebSocket 连接成功!")
            
            # 测试1: 使用适配器默认的订阅方法
            print(f"\n3. 测试1: 使用适配器默认订阅方法")
            print(f"   订阅市场: {market_ids}")
            
            # 检查订阅前的状态
            print(f"   订阅前 subscription_status: {adapter.subscription_status}")
            
            # 使用适配器实际存在的订阅方法
            try:
                # 直接调用 _do_subscribe 方法，确保传递正确的参数
                await adapter._do_subscribe(market_ids, SubscriptionType.ORDERBOOK)
                print(f"   ✅ 使用 _do_subscribe 方法订阅订单簿: {market_ids}")
            except Exception as e:
                print(f"   ❌ 订阅失败: {e}")
            
            # 检查订阅后的状态
            print(f"   订阅后 subscription_status: {adapter.subscription_status}")
            
            # 等待数据
            print("   等待数据 (15秒)...")
            for i in range(15):
                await asyncio.sleep(1)
                if received_data:
                    print(f"   ✅ 第{i+1}秒: 收到 {len(received_data)} 条数据")
                    break
                else:
                    print(f"   ⏳ 第{i+1}秒: 等待中...")
            
            default_method_count = len(received_data)
            print(f"   默认方法收到 {default_method_count} 条数据")
            
            # 如果默认方法失败，测试直接发送消息
            if default_method_count == 0:
                print(f"\n4. 测试失败: 默认方法未收到任何数据")
            else:
                print("✅ 默认订阅方法工作正常!")
                
        else:
            print("❌ WebSocket 连接失败")
            
    except Exception as e:
        print(f"❌ 测试异常: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await ws_manager.stop()

async def analyze_adapter_behavior():
    """分析适配器行为"""
    print("\n=== 分析适配器行为 ===")
    
    adapter = PolymarketAdapter()
    
    print("1. 检查适配器状态:")
    print(f"   - 名称: {adapter.name}")
    print(f"   - 交易所: {adapter.exchange_type}")
    print(f"   - 是否连接: {adapter.is_connected}")
    print(f"   - 已订阅状态: {adapter.subscription_status}")
    
    print("\n2. 检查连接器配置:")
    for sub_type, config in adapter._subscription_config.items():
        print(f"   - {sub_type.value}: {config.get('endpoint')}")
        print(f"     消息格式: {config.get('message_format')}")
    
    print("\n3. 测试连接和订阅流程:")
    try:
        # 测试连接 - 使用实际存在的方法
        print("   测试连接所有端点...")
        if hasattr(adapter, 'connect_all'):
            connected = await adapter.connect_all()
        elif hasattr(adapter, 'connect'):
            connected = await adapter.connect()
        else:
            print("   ❌ 没有找到可用的连接方法")
            return
            
        print(f"   连接结果: {connected}")
        
        if connected:
            # 检查连接状态
            status = adapter.get_connection_status()
            print(f"   连接状态: {status}")
            
            # 测试订阅 - 使用实际存在的方法
            market_ids = ["0x04c3f66c7cf5e27f3f4d1b438d4ef7c89f7e406e"]
            print(f"   测试订阅订单簿: {market_ids}")
            
            try:
                # 尝试使用公共的 subscribe 方法
                await adapter.subscribe(market_ids)
                print("   ✅ 使用 subscribe 方法订阅成功")
            except (AttributeError, Exception) as e:
                print(f"   ⚠️ subscribe 方法不可用: {e}")
                try:
                    # 尝试直接调用内部方法
                    await adapter._do_subscribe(market_ids, SubscriptionType.ORDERBOOK)
                    print("   ✅ 使用 _do_subscribe 方法订阅成功")
                except Exception as e2:
                    print(f"   ❌ 所有订阅方法都失败: {e2}")
            
            # 检查订阅状态
            print(f"   订阅后状态: {adapter.subscription_status}")
            
            # 等待一会儿看是否有数据
            print("   等待数据 (3秒)...")
            await asyncio.sleep(3)
            
            # 断开连接
            if hasattr(adapter, 'disconnect_all'):
                await adapter.disconnect_all()
            elif hasattr(adapter, 'disconnect'):
                await adapter.disconnect()
                
            print("   ✅ 连接和订阅流程测试完成")
        else:
            print("   ❌ 连接失败，跳过订阅测试")
            
    except Exception as e:
        print(f"   ❌ 测试过程中出错: {e}")
        import traceback
        traceback.print_exc()

async def test_multiple_connectors():
    """测试多连接器的独立操作"""
    print("\n=== 测试多连接器独立操作 ===")
    
    adapter = PolymarketAdapter()
    
    # 测试连接所有端点
    print("1. 连接所有端点...")
    if hasattr(adapter, 'connect_all'):
        connected = await adapter.connect_all()
    elif hasattr(adapter, 'connect'):
        connected = await adapter.connect()
    else:
        print("   ❌ 没有找到可用的连接方法")
        return
        
    print(f"   连接结果: {connected}")
    
    if connected:
        # 检查连接状态
        status = adapter.get_connection_status()
        print(f"   连接状态: {json.dumps(status, indent=2, default=str)}")
        
        # 测试单个连接器的订阅
        market_ids = ["0x04c3f66c7cf5e27f3f4d1b438d4ef7c89f7e406e"]
        
        print(f"\n2. 测试订单簿订阅: {market_ids}")
        try:
            if hasattr(adapter, 'subscribe'):
                await adapter.subscribe(market_ids)
            else:
                await adapter._do_subscribe(market_ids, SubscriptionType.ORDERBOOK)
            print("   ✅ 订单簿订阅成功")
        except Exception as e:
            print(f"   ❌ 订单簿订阅失败: {e}")
        
        print(f"\n3. 测试交易数据订阅: {market_ids}")
        try:
            # 对于多连接器架构，可能需要分别订阅不同类型
            await adapter._do_subscribe(market_ids, SubscriptionType.TRADES)
            print("   ✅ 交易数据订阅成功")
        except Exception as e:
            print(f"   ❌ 交易数据订阅失败: {e}")
        
        # 等待一段时间
        await asyncio.sleep(3)
        
        # 检查订阅状态
        status = adapter.get_connection_status()
        print(f"   最终连接状态: {json.dumps(status, indent=2, default=str)}")
        
        # 断开连接
        if hasattr(adapter, 'disconnect_all'):
            await adapter.disconnect_all()
        elif hasattr(adapter, 'disconnect'):
            await adapter.disconnect()
        print("✅ 已断开所有连接")

async def main():
    """主调试函数"""
    print("🚀 Polymarket 真实适配器调试")

    #await debug_gamma_api()
   
    # 1. 分析适配器行为
    await analyze_adapter_behavior()
    
    # 2. 测试多连接器独立操作
    #await test_multiple_connectors()

    # 3. 测试真实的订阅功能
    #await debug_polymarket_subscription()
 
    print("\n=== 调试完成 ===")
    print("总结:")
    print("1. 测试了真实的 PolymarketAdapter 多连接器架构")
    print("2. 检查了适配器的订阅状态管理")
    print("3. 测试了多种订阅格式")
    print("4. 分析了适配器消息处理能力")
    print("5. 测试了多连接器的独立操作")


if __name__ == "__main__":
    asyncio.run(main())