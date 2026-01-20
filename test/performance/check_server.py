#!/usr/bin/env python3
"""
独立测试Dashboard是否能接收WebSocket数据
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

import asyncio
import json
import time
import threading
import logging

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("test_dashboard")

# 导入Dashboard的WebSocket客户端
from market.monitor.dashboard import WebSocketMonitorClient

class TestDashboardClient:
    """测试Dashboard客户端"""
    
    def __init__(self, uri="ws://localhost:9999/ws"):
        self.uri = uri
        self.client = WebSocketMonitorClient(uri)
        self.client.add_callback(self.on_data)
        self.data_received = False
        self.message_count = 0
    
    def on_data(self, data):
        """数据回调函数"""
        self.message_count += 1
        self.data_received = True
        msg_type = data.get('type')
        logger.info(f"[TestDashboardClient] 收到数据 #{self.message_count}: 类型={msg_type}")
        
        if msg_type == 'metrics_update':
            summary = data.get('data', {}).get('summary', {})
            logger.info(f"  适配器数量: {len(summary)}")
            for adapter in summary.keys():
                logger.info(f"  - {adapter}")
    
    def start(self):
        """启动客户端"""
        logger.info(f"启动Dashboard客户端，URI: {self.uri}")
        self.client.start()
        
        # 等待连接建立
        time.sleep(2)
        
        logger.info(f"客户端连接状态: {self.client.connected}")
        logger.info(f"客户端是否运行: {self.client.running}")
        
        # 等待一段时间接收数据
        logger.info("等待接收数据...")
        for i in range(30):  # 等待30秒
            if self.data_received:
                logger.info(f"成功收到数据！收到 {self.message_count} 条消息")
                return True
            time.sleep(1)
            logger.info(f"等待数据... ({i+1}/30)")
        
        logger.warning("30秒内未收到数据")
        return False
    
    def stop(self):
        """停止客户端"""
        self.client.stop()

def main():
    print("=== 测试Dashboard WebSocket客户端 ===")
    print("请确保压力测试正在运行...")
    
    test_client = TestDashboardClient()
    
    try:
        if test_client.start():
            print("✅ Dashboard客户端能正常接收数据")
            print(f"   收到 {test_client.message_count} 条消息")
        else:
            print("❌ Dashboard客户端未能接收数据")
            print("\n可能的原因:")
            print("  1. WebSocket服务器没有发送数据")
            print("  2. 客户端连接失败")
            print("  3. 回调函数有问题")
    finally:
        test_client.stop()
        print("测试完成")

if __name__ == "__main__":
    main()