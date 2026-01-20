#!/usr/bin/env python3
"""
24小时市场适配器压力测试 - WebSocket版本
运行此脚本进行长时间测试，实时通过WebSocket推送数据
"""

import asyncio
import time
import sys
import os
import signal
import json
from datetime import datetime, timedelta
from pathlib import Path
from enum import Enum
import logging

# 添加src目录到路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from market.monitor.collector import MarketMonitor
from market.adapter.binance_adapter import BinanceAdapter
from market.adapter.polymarket_adapter import PolymarketAdapter
from market.service.ws_manager import WebSocketManager

# WebSocket管理器（用于向前端推送数据）
class WebSocketBroadcaster:
    """WebSocket广播器"""
    
    def __init__(self):
        self.connected_clients = set()
        self.latest_data = {}
        
    async def connect(self, websocket):
        """处理新连接"""
        await websocket.accept()
        self.connected_clients.add(websocket)
        logging.info(f"新的WebSocket连接，当前连接数: {len(self.connected_clients)}")
        
        # 发送最新数据
        if self.latest_data:
            await websocket.send_json(self.latest_data)
            
    async def disconnect(self, websocket):
        """断开连接"""
        if websocket in self.connected_clients:
            self.connected_clients.remove(websocket)
        logging.info(f"WebSocket断开，当前连接数: {len(self.connected_clients)}")
        
    async def broadcast(self, data):
        """广播数据到所有客户端"""
        self.latest_data = data
        disconnected = []
        
        for client in self.connected_clients:
            try:
                await client.send_json(data)
            except:
                disconnected.append(client)
                
        # 清理断开连接的客户端
        for client in disconnected:
            await self.disconnect(client)


class WebSocketStressTest:
    """WebSocket版本压力测试"""
    
    def __init__(self, duration_hours: float = 1.0):
        self.duration_hours = duration_hours
        self.end_time = None
        self.is_running = True
        
        # WebSocket广播器
        self.broadcaster = WebSocketBroadcaster()
        
        # 测试结果文件
        self.test_dir = Path("./tests/performance/results")
        self.test_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.log_file = self.test_dir / f"stress_test_{timestamp}.log"
        self.metrics_file = self.test_dir / f"metrics_{timestamp}.json"
        
        # 创建监控器
        self.monitor = MarketMonitor()
        
        # 设置信号处理
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
        
        # 设置日志
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[
                logging.StreamHandler(),
                logging.FileHandler(str(self.log_file))
            ]
        )
        self.logger = logging.getLogger(__name__)
    
    def _signal_handler(self, signum, frame):
        """处理中断信号"""
        self.logger.info(f"\n收到信号 {signum}，正在停止测试...")
        self.is_running = False
    
    async def broadcast_metrics(self):
        """定期广播监控指标"""
        while self.is_running:
            try:
                summary = self.monitor.get_summary()
                
                # 准备广播消息
                message = {
                    'type': 'metrics_update',
                    'timestamp': datetime.now().isoformat(),
                    'data': {
                        'summary': self._make_serializable(summary),
                        'test_info': {
                            'duration_hours': self.duration_hours,
                            'elapsed_hours': (datetime.now() - self.start_time).seconds / 3600 if hasattr(self, 'start_time') else 0,
                            'status': 'running'
                        }
                    }
                }
                
                await self.broadcaster.broadcast(message)
                
            except Exception as e:
                self.logger.error(f"广播数据出错: {e}")
                
            await asyncio.sleep(1)  # 每秒广播一次
    
    def _make_serializable(self, obj):
        """将对象转换为可JSON序列化的格式"""
        if isinstance(obj, (str, int, float, bool, type(None))):
            return obj
        elif isinstance(obj, Enum):
            return obj.name if hasattr(obj, 'name') else str(obj)
        elif isinstance(obj, dict):
            return {k: self._make_serializable(v) for k, v in obj.items()}
        elif isinstance(obj, (list, tuple)):
            return [self._make_serializable(item) for item in obj]
        elif hasattr(obj, '__dict__'):
            try:
                return self._make_serializable(obj.__dict__)
            except:
                return str(obj)
        else:
            return str(obj)
    
    async def _save_metrics(self, stats_collection):
        """保存指标到JSON文件"""
        try:
            with open(self.metrics_file, 'w', encoding='utf-8') as f:
                json.dump(stats_collection, f, indent=2, ensure_ascii=False)
        except Exception as e:
            self.logger.error(f"保存指标时出错: {e}")
    
    async def run(self):
        """运行压力测试"""
        self.logger.info(f"=== 开始 {self.duration_hours} 小时压力测试 ===")
        self.logger.info(f"日志文件: {self.log_file}")
        self.logger.info(f"指标文件: {self.metrics_file}")
        self.logger.info("WebSocket数据推送: ws://localhost:8000/ws")
        self.logger.info("访问 http://localhost:8000 查看实时监控")
        
        # 计算结束时间
        self.end_time = datetime.now() + timedelta(hours=self.duration_hours)
        self.start_time = datetime.now()
        self.logger.info(f"预计结束时间: {self.end_time}")
        
        try:
            # 创建适配器
            binance = BinanceAdapter()
            polymarket = PolymarketAdapter()
            
            # 设置监控器
            binance.set_monitor(self.monitor)
            polymarket.set_monitor(self.monitor)
            
            # 手动向监控器注册适配器
            self.monitor.register_adapter('binance', binance)
            self.monitor.register_adapter('polymarket', polymarket)
            
            # 创建WebSocket管理器（市场数据）
            ws_manager = WebSocketManager()
            ws_manager.register_adapter('binance', binance)
            ws_manager.register_adapter('polymarket', polymarket)
            
            # 启动连接
            self.logger.info("启动市场数据连接...")
            await ws_manager.start()
            await asyncio.sleep(3)  # 等待连接建立
            
            # 订阅交易对
            self.logger.info("订阅交易对...")
            binance_symbols = ['BTCUSDT', 'ETHUSDT']
            await binance.subscribe(binance_symbols)
            
            # 尝试订阅Polymarket
            try:
                market_ids = await polymarket.get_active_market_id(3)
                if market_ids:
                    await polymarket.subscribe(market_ids)
                    self.logger.info(f"已订阅Polymarket市场: {market_ids}")
                else:
                    self.logger.warning("未获取到Polymarket市场ID")
            except Exception as e:
                self.logger.warning(f"Polymarket订阅失败: {e}")
            
            # 等待一段时间确保数据开始流动
            await asyncio.sleep(5)
            
            self.logger.info(f"\n✅ 测试已启动，运行 {self.duration_hours} 小时")
            self.logger.info("📊 WebSocket正在实时推送监控数据")
            self.logger.info("⏳ 正在收集性能数据...\n")
            
            # 启动广播任务
            broadcast_task = asyncio.create_task(self.broadcast_metrics())
            
            # 实时监控循环
            stats_collection = []
            start_time = time.time()
            last_progress_update = start_time
            last_save_time = start_time
            
            # 运行时间统计
            total_seconds = self.duration_hours * 3600
            
            while self.is_running and time.time() - start_time < total_seconds:
                try:
                    current_time = time.time()
                    elapsed = current_time - start_time
                    
                    # 每10秒更新控制台进度
                    if current_time - last_progress_update >= 10:
                        elapsed_str = self._format_time(elapsed)
                        remaining_str = self._format_time(total_seconds - elapsed)
                        
                        # 获取当前状态
                        summary = self.monitor.get_summary()
                        
                        # 构建状态字符串
                        status_parts = []
                        for adapter in ['binance', 'polymarket']:
                            if adapter in summary:
                                metrics = summary[adapter]
                                success = metrics.get('success_rate', 0) * 100
                                latency = max(metrics.get('avg_latency_ms', 0), 0)
                                connected = metrics.get('is_connected', False)
                                status = f"{adapter}:{success:.0f}%/{latency:.0f}ms"
                                status_parts.append(f"{'✅' if connected else '❌'} {status}")
                        
                        status_line = " | ".join(status_parts) if status_parts else "等待数据..."
                        
                        print(f"\r⏱️  {elapsed_str} / {remaining_str} | 📊 {status_line}", end='', flush=True)
                        last_progress_update = current_time
                    
                    # 每30秒保存一次数据
                    if current_time - last_save_time >= 30:
                        summary = self.monitor.get_summary()
                        current_stats = {
                            'timestamp': datetime.now().isoformat(),
                            'elapsed_hours': elapsed / 3600,
                            'summary': summary
                        }
                        stats_collection.append(current_stats)
                        
                        # 异步保存数据
                        asyncio.create_task(self._save_metrics(stats_collection))
                        last_save_time = current_time
                    
                    await asyncio.sleep(1)
                    
                except Exception as e:
                    self.logger.error(f"监控循环出错: {e}")
                    await asyncio.sleep(5)
            
            # 测试完成
            print("\n\n" + "="*60)
            self.logger.info("✅ 测试完成！")
            
            # 显示最终统计
            final_summary = self.monitor.get_summary()
            print("\n🎯 最终性能统计:")
            print("-"*40)
            
            for adapter, metrics in final_summary.items():
                adapter_type = metrics.get('adapter_type', 'unknown')
                latency = max(metrics.get('avg_latency_ms', 0), 0)
                success = metrics.get('success_rate', 0) * 100
                
                print(f"\n  {adapter.upper()} ({adapter_type}):")
                print(f"    ✅ 成功率: {success:.1f}%")
                print(f"    ⏱️  平均延迟: {latency:.1f}ms")
                
                if adapter_type == 'binance':
                    total = metrics.get('validations_total', 0)
                    valid = metrics.get('validations_valid', 0)
                    if total > 0:
                        print(f"    🔍 验证: {valid}/{total} ({valid/total*100:.1f}%)")
                    else:
                        print(f"    🔍 验证: 0/0 (0.0%)")
                else:
                    received = metrics.get('messages_received', 0)
                    processed = metrics.get('messages_processed', 0)
                    if received > 0:
                        print(f"    📨 消息: {processed}/{received} ({processed/received*100:.1f}% 已处理)")
                    else:
                        print(f"    📨 消息: 0/0 (0.0% 已处理)")
                
                connected = metrics.get('is_connected', False)
                print(f"    🔌 连接状态: {'✅ 已连接' if connected else '❌ 未连接'}")
            
            # 保存最终数据
            if stats_collection:
                await self._save_metrics(stats_collection)
                self.logger.info(f"最终数据已保存: {self.metrics_file}")
            
            print("\n🌐 监控界面访问信息:")
            print(f"   访问 http://localhost:8000 查看历史数据")
            print("="*60)
            
            # 清理资源
            self.logger.info("清理资源...")
            broadcast_task.cancel()
            await ws_manager.stop()
            
            # 发送测试完成消息
            await self.broadcaster.broadcast({
                'type': 'test_complete',
                'timestamp': datetime.now().isoformat(),
                'message': f'压力测试已完成，运行时长: {self.duration_hours}小时'
            })
            
        except Exception as e:
            self.logger.error(f"测试失败: {e}")
            import traceback
            traceback.print_exc()
    
    def _format_time(self, seconds):
        """格式化时间显示"""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"


async def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description='运行市场适配器压力测试（WebSocket版本）')
    parser.add_argument('--hours', type=float, default=1.0,
                       help='测试时长（小时），默认1小时')
    parser.add_argument('--quick', action='store_true',
                       help='快速测试模式（5分钟）')
    parser.add_argument('--long', action='store_true',
                       help='长期测试模式（24小时）')
    
    args = parser.parse_args()
    
    # 确定测试时长
    if args.long:
        duration = 24.0
    elif args.quick:
        duration = 5.0 / 60.0  # 5分钟
    else:
        duration = args.hours
    
    print(f"=== 开始 {duration} 小时压力测试 ===")
    print("📊 WebSocket实时数据推送已启用")
    print("🌐 访问 http://localhost:8000 查看实时监控")
    print("按 Ctrl+C 停止测试\n")
    
    test = WebSocketStressTest(duration_hours=duration)
    
    await test.run()


if __name__ == "__main__":
    asyncio.run(main())