import asyncio
import logging
import sys
import os
from decimal import Decimal

# 添加 src 目录到 Python 路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from market import PolymarketAdapter, WebSocketManager, MarketRouter, MarketData

# 配置详细日志
logging.basicConfig(
    level=logging.DEBUG,  # 改为 DEBUG 级别
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

async def debug_polymarket_connection():
    """调试 Polymarket 连接问题"""
    print("=== 开始调试 Polymarket 连接 ===")
    
    polymarket = PolymarketAdapter()
    ws_manager = WebSocketManager()
    market_router = MarketRouter()
    
    print("1. 适配器创建完成")
    
    # 注册适配器
    ws_manager.register_adapter('polymarket', polymarket)
    market_router.register_adapter('polymarket', polymarket)
    print("2. 适配器注册完成")
    
    # 用于收集接收到的数据
    received_data = []
    
    def on_market_data(data: MarketData):
        """市场数据回调"""
        print(f"📊 收到市场数据: {data.symbol}")
        if data.orderbook:
            print(f"   订单簿: {len(data.orderbook.bids)} bids, {len(data.orderbook.asks)} asks")
            if data.orderbook.bids and data.orderbook.asks:
                spread = data.orderbook.get_spread()
                print(f"   点差: {spread}")
        if data.last_price:
            print(f"   最新价格: {data.last_price}")
        if data.last_trade:
            print(f"   最新交易: {data.last_trade.quantity} @ {data.last_trade.price}")
        received_data.append(data)
    
    market_router.add_callback(on_market_data)
    print("3. 回调函数注册完成")
    
    try:
        print("4. 开始连接...")
        await ws_manager.start()
        print("5. 连接启动完成")
        
        # 等待连接建立
        print("6. 等待连接建立...")
        await asyncio.sleep(5)
        
        status = ws_manager.get_connection_status()
        print(f"7. 连接状态: {status}")
        
        if status.get('polymarket', False):
            print("✅ Polymarket 连接成功!")
            
            # 尝试获取市场列表
            print("8. 尝试获取市场列表...")
            try:
                markets = await polymarket.get_market_list(limit=3)
                print(f"   获取到 {len(markets)} 个市场")
                for market in markets:
                    print(f"   - {market.get('id', 'Unknown')}: {market.get('question', 'No question')}")
                
                # 使用真实市场ID订阅
                if markets:
                    market_ids = [market['id'] for market in markets if market.get('id')]
                    symbols = market_ids[:2]  # 取前2个市场
                else:
                    # 如果获取失败，使用测试市场ID
                    symbols = ["0x4d792047616d65206f66205468756d62", "0x1234567890abcdef1234567890abcdef12345678"]
                    print(f"   使用测试市场ID: {symbols}")
            except Exception as e:
                print(f"   ❌ 获取市场列表失败: {e}")
                symbols = ["0x4d792047616d65206f66205468756d62", "0x1234567890abcdef1234567890abcdef12345678"]
                print(f"   使用测试市场ID: {symbols}")
            
            # 测试订阅
            print(f"9. 订阅市场: {symbols}")
            await ws_manager.subscribe_all(symbols)
            
            # 等待一段时间看是否收到数据
            print("10. 等待接收数据（20秒）...")
            for i in range(20):
                await asyncio.sleep(1)
                print(f"    已等待 {i+1} 秒，收到 {len(received_data)} 条数据")
                
                # 每5秒输出一次详细状态
                if (i + 1) % 5 == 0:
                    current_status = ws_manager.get_connection_status()
                    print(f"    📈 当前状态: {current_status}")
                    
                    # 输出性能统计
                    if hasattr(polymarket, 'performance_stats'):
                        stats = polymarket.performance_stats
                        print(f"    📊 性能统计: {stats.get('messages_per_second', 0):.1f} msg/s, "
                              f"延迟: {stats.get('average_latency', 0):.2f}ms")
            
            print(f"11. 数据接收统计: 总共收到 {len(received_data)} 条数据")
            
            if received_data:
                print("✅ 成功接收到数据!")
                # 显示前几条数据的详细信息
                for i, data in enumerate(received_data[:3]):
                    print(f"   数据 #{i+1}:")
                    print(f"     - 市场: {data.symbol}")
                    print(f"     - 时间: {data.timestamp}")
                    print(f"     - 价格: {data.last_price}")
                    if data.orderbook:
                        print(f"     - 订单簿: {len(data.orderbook.bids)} bids, {len(data.orderbook.asks)} asks")
            else:
                print("❌ 未收到任何数据")
                
        else:
            print("❌ Polymarket 连接失败")
            
            # 输出详细的错误信息
            print("12. 详细连接状态:")
            detailed_status = polymarket.get_connection_status() if hasattr(polymarket, 'get_connection_status') else {}
            print(f"    详细状态: {detailed_status}")
            
    except Exception as e:
        print(f"❌ 连接过程中出现异常: {e}")
        import traceback
        traceback.print_exc()
    finally:
        print("13. 清理资源...")
        await ws_manager.stop()
        print("14. 调试完成")

async def debug_polymarket_market_list():
    """单独测试市场列表获取"""
    print("\n=== 测试 Polymarket 市场列表获取 ===")
    
    polymarket = PolymarketAdapter()
    
    try:
        print("1. 获取市场列表...")
        markets = await polymarket.get_market_list(limit=10)
        
        print(f"2. 获取到 {len(markets)} 个市场")
        
        for i, market in enumerate(markets):
            print(f"   {i+1}. ID: {market.get('id', 'N/A')}")
            print(f"      问题: {market.get('question', 'N/A')}")
            print(f"      状态: {market.get('status', 'N/A')}")
            if 'volume' in market:
                print(f"      交易量: {market.get('volume', 'N/A')}")
            print()
            
    except Exception as e:
        print(f"❌ 获取市场列表失败: {e}")
        import traceback
        traceback.print_exc()

async def debug_polymarket_detailed():
    """详细调试 Polymarket 各个组件"""
    print("\n=== 详细调试 Polymarket 组件 ===")
    
    polymarket = PolymarketAdapter()
    
    print("1. 检查适配器属性:")
    print(f"   - 名称: {polymarket.name}")
    print(f"   - 交易所类型: {polymarket.exchange_type}")
    print(f"   - 是否连接: {polymarket.is_connected}")
    print(f"   - WebSocket URLs: {getattr(polymarket, 'ws_urls', 'N/A')}")
    print(f"   - 已订阅符号: {getattr(polymarket, 'subscribed_symbols', 'N/A')}")
    
    print("2. 检查连接器:")
    if hasattr(polymarket, 'connector'):
        connector = polymarket.connector
        print(f"   - 连接器类型: {type(connector)}")
        print(f"   - URL: {getattr(connector, 'url', 'N/A')}")
    else:
        print("   - 没有找到连接器")
    
    print("3. 测试市场列表API...")
    try:
        markets = await polymarket.get_market_list(limit=3)
        print(f"   ✅ 成功获取 {len(markets)} 个市场")
    except Exception as e:
        print(f"   ❌ 获取失败: {e}")

async def main():
    """运行所有调试测试"""
    print("🚀 启动 Polymarket 调试工具")
    
    # 运行详细组件调试
    await debug_polymarket_detailed()
    
    # 运行市场列表调试
    await debug_polymarket_market_list()
    
    # 运行主连接调试
    await debug_polymarket_connection()
    
    print("\n🎉 所有调试测试完成!")

if __name__ == "__main__":
    asyncio.run(main())