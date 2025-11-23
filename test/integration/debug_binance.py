import asyncio
import logging
import sys
import os

# 添加 src 目录到 Python 路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from market import BinanceAdapter, WebSocketManager

# 配置详细日志
logging.basicConfig(
    level=logging.DEBUG,  # 改为 DEBUG 级别
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

async def debug_connection():
    """调试连接问题"""
    print("=== 开始调试币安连接 ===")
    
    binance = BinanceAdapter()
    ws_manager = WebSocketManager()
    
    print("1. 适配器创建完成")
    
    ws_manager.register_adapter('binance', binance)
    print("2. 适配器注册完成")
    
    try:
        print("3. 开始连接...")
        await ws_manager.start()
        print("4. 连接启动完成")
        
        # 等待连接建立
        await asyncio.sleep(5)
        
        status = ws_manager.get_connection_status()
        print(f"5. 连接状态: {status}")
        
        if status['binance']:
            print("✅ 连接成功!")
            
            # 测试订阅
            symbols = ['BTCUSDT']
            print(f"6. 订阅交易对: {symbols}")
            await ws_manager.subscribe_all(symbols)
            
            # 等待一段时间看是否收到数据
            print("7. 等待接收数据...")
            await asyncio.sleep(10)
            
        else:
            print("❌ 连接失败")
            
    except Exception as e:
        print(f"❌ 连接过程中出现异常: {e}")
        import traceback
        traceback.print_exc()
    finally:
        print("8. 清理资源...")
        await ws_manager.stop()
        print("9. 调试完成")

if __name__ == "__main__":
    asyncio.run(debug_connection())