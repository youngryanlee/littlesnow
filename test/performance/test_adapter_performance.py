# tests/performance/test_adapter_performance.py
#!/usr/bin/env python3
"""
增强版集成压力测试脚本 - 结合两个版本的优点
"""
import asyncio
import sys
import os
import signal
import json
import logging
import argparse
from datetime import datetime, timedelta
from pathlib import Path
import time

# 添加src目录到路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from market.monitor.service import MonitorService
from market.monitor.collector import MarketMonitor
from market.adapter.binance_adapter import BinanceAdapter
from market.adapter.polymarket_adapter import PolymarketAdapter
from market.service.ws_manager import WebSocketManager

class StressTest:
    """增强版压力测试 - 正确的数据流"""
    
    def __init__(self, duration_hours: float = 1.0, auto_start_websocket: bool = True):
        self.duration_hours = duration_hours
        self.auto_start_websocket = auto_start_websocket
        
        # 测试结果文件
        self.test_dir = Path("./tests/performance/results")
        self.test_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.log_file = self.test_dir / f"stress_test_{timestamp}.log"
        self.metrics_file = self.test_dir / f"metrics_{timestamp}.json"
        
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
        
        # 创建监控器（数据收集器）
        self.monitor = MarketMonitor()
        
        # 创建适配器并设置监控器
        self.binance_adapter = BinanceAdapter()
        self.polymarket_adapter = PolymarketAdapter()
        
        # 设置监控器
        self.binance_adapter.set_monitor(self.monitor)
        self.polymarket_adapter.set_monitor(self.monitor)
        
        # 注册适配器到监控器
        self.monitor.register_adapter('binance', self.binance_adapter)
        self.monitor.register_adapter('polymarket', self.polymarket_adapter)
        
        # 创建WebSocket管理器（用于市场数据）
        self.ws_manager = WebSocketManager()
        self.ws_manager.register_adapter('binance', self.binance_adapter)
        self.ws_manager.register_adapter('polymarket', self.polymarket_adapter)
        
        # 创建监控服务（只负责显示）
        self.monitor_service = MonitorService(
            host="0.0.0.0",
            port=8000,
            auto_start_websocket=auto_start_websocket,
            open_browser=True
        )
        
        # 传递监控器到监控服务
        self.monitor_service.set_monitor(self.monitor)
        
        # 状态跟踪
        self.stats_collection = []
        self.start_time = None
        self.is_running = False
        
        # 信号处理
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
    
    def _signal_handler(self, signum, frame):
        """处理中断信号"""
        self.logger.info(f"\n收到信号 {signum}，正在停止测试...")
        self.is_running = False
        asyncio.create_task(self.stop())
    
    async def _save_metrics(self):
        """保存指标到JSON文件"""
        try:
            with open(self.metrics_file, 'w', encoding='utf-8') as f:
                json.dump(self.stats_collection, f, indent=2, ensure_ascii=False)
            self.logger.info(f"指标数据已保存: {self.metrics_file}")
        except Exception as e:
            self.logger.error(f"保存指标时出错: {e}")
    
    def _format_time(self, seconds):
        """格式化时间显示"""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    
    async def _display_progress(self):
        """显示测试进度"""
        while self.is_running and self.monitor_service.is_running:
            try:
                current_time = time.time()
                elapsed = current_time - self.start_time
                total_seconds = self.duration_hours * 3600
                
                # 每10秒更新一次进度
                if int(current_time) % 10 == 0:
                    elapsed_str = self._format_time(elapsed)
                    remaining_str = self._format_time(total_seconds - elapsed)
                    
                    # 获取当前指标
                    metrics = self.monitor.get_summary()
                    
                    # 构建状态字符串
                    status_parts = []
                    for adapter_name, adapter_metrics in metrics.items():
                        if adapter_metrics:
                            success = adapter_metrics.get('success_rate', 0) * 100
                            latency = max(adapter_metrics.get('avg_latency_ms', 0), 0)
                            connected = adapter_metrics.get('is_connected', False)
                            messages = adapter_metrics.get('messages_received', 0)
                            status = f"{adapter_name}:{messages}msg/{latency:.0f}ms/{success:.0f}%"
                            status_parts.append(f"{'✅' if connected else '❌'} {status}")
                    
                    status_line = " | ".join(status_parts) if status_parts else "等待数据..."
                    print(f"\r⏱️  {elapsed_str} / {remaining_str} | 📊 {status_line}", end='', flush=True)
                
                # 每30秒保存一次数据
                if int(current_time) % 30 == 0:
                    summary = self.monitor.get_summary()
                    current_stats = {
                        'timestamp': datetime.now().isoformat(),
                        'elapsed_hours': elapsed / 3600,
                        'summary': summary
                    }
                    self.stats_collection.append(current_stats)
                    
                    # 异步保存数据
                    asyncio.create_task(self._save_metrics())
                
                await asyncio.sleep(1)
                
            except Exception as e:
                self.logger.error(f"进度显示出错: {e}")
                await asyncio.sleep(5)
    
    async def _subscribe_data(self):
        """订阅数据源"""
        try:
            # 订阅Binance
            symbols = ['BTCUSDT', 'ETHUSDT']
            await self.binance_adapter.subscribe(symbols)
            self.logger.info(f"✅ Binance订阅完成: {symbols}")
            
            # 订阅Polymarket
            try:
                market_ids = await self.polymarket_adapter.get_active_market_id(3)
                if not market_ids:
                    market_ids = ["0x14bb1f6af987e0c27e9d6bb538f13a7cfeb0ca2b"]  # 备用市场ID
                
                if market_ids:
                    await self.polymarket_adapter.subscribe(market_ids)
                    self.logger.info(f"✅ Polymarket订阅完成: {market_ids}")
                else:
                    self.logger.error("❌ 无法订阅Polymarket: 未找到市场ID")
                    
            except Exception as e:
                self.logger.error(f"❌ Polymarket订阅失败: {e}")
                
        except Exception as e:
            self.logger.error(f"❌ 订阅数据失败: {e}")
            raise
    
    async def run(self):
        """运行压力测试"""
        self.logger.info(f"=== 开始 {self.duration_hours} 小时压力测试 ===")
        self.logger.info(f"日志文件: {self.log_file}")
        self.logger.info(f"指标文件: {self.metrics_file}")
        
        if self.auto_start_websocket:
            self.logger.info("📊 自动启动WebSocket服务器和前端")
            self.logger.info(f"🌐 前端地址: http://localhost:8000")
        else:
            self.logger.info("📊 手动模式: 请确保WebSocket服务器已启动")
        
        # 计算结束时间
        self.end_time = datetime.now() + timedelta(hours=self.duration_hours)
        self.start_time = time.time()
        self.logger.info(f"预计结束时间: {self.end_time}")
        
        try:
            # 启动市场数据连接
            self.logger.info("启动市场数据连接...")
            await self.ws_manager.start()
            await asyncio.sleep(2)
            
            # 订阅数据
            self.logger.info("订阅数据源...")
            await self._subscribe_data()
            
            # 启动监控显示服务
            self.logger.info("启动监控显示服务...")
            success = await self.monitor_service.start_monitoring(
                duration_hours=self.duration_hours
            )
            
            if not success:
                self.logger.error("❌ 启动监控显示服务失败")
                return
            
            self.is_running = True
            
            self.logger.info(f"\n✅ 测试已启动，运行 {self.duration_hours} 小时")
            self.logger.info("📊 数据正在收集和推送...")
            self.logger.info("⏳ 正在收集性能数据...\n")
            
            # 启动进度显示任务
            progress_task = asyncio.create_task(self._display_progress())
            
            # 等待测试完成
            try:
                while self.is_running and self.monitor_service.is_running:
                    await asyncio.sleep(1)
            except KeyboardInterrupt:
                self.logger.info("\n测试被用户中断")
            
            # 停止进度显示
            progress_task.cancel()
            
            # 测试完成
            print("\n\n" + "="*60)
            self.logger.info("✅ 测试完成！")
            
            # 显示最终统计
            self._display_final_stats()
            
            # 保存最终数据
            if self.stats_collection:
                await self._save_metrics()
            
            print("\n🌐 监控界面访问信息:")
            print(f"   访问 http://localhost:8000 查看历史数据")
            print("="*60)
            
        except Exception as e:
            self.logger.error(f"测试失败: {e}")
            import traceback
            traceback.print_exc()
        finally:
            await self.stop()
    
    def _display_final_stats(self):
        """显示最终统计"""
        if not self.stats_collection:
            print("没有收集到数据")
            return
        
        # 获取最后一次的数据
        final_data = self.stats_collection[-1] if self.stats_collection else {}
        summary = final_data.get('summary', {})
        
        print("\n🎯 最终性能统计:")
        print("-"*40)
        
        for adapter, metrics in summary.items():
            adapter_type = metrics.get('adapter_type', 'unknown')
            latency = max(metrics.get('avg_latency_ms', 0), 0)
            success = metrics.get('success_rate', 0) * 100
            messages = metrics.get('messages_received', 0)
            
            print(f"\n  {adapter.upper()} ({adapter_type}):")
            print(f"    ✅ 成功率: {success:.1f}%")
            print(f"    ⏱️  平均延迟: {latency:.1f}ms")
            print(f"    📨 消息数: {messages}")
            
            if adapter_type == 'binance':
                total = metrics.get('validations_total', 0)
                valid = metrics.get('validations_valid', 0)
                if total > 0:
                    print(f"    🔍 验证: {valid}/{total} ({valid/total*100:.1f}%)")
            
            connected = metrics.get('is_connected', False)
            print(f"    🔌 连接状态: {'✅ 已连接' if connected else '❌ 未连接'}")
    
    async def stop(self):
        """停止测试"""
        # 停止市场数据连接
        if hasattr(self, 'ws_manager'):
            await self.ws_manager.stop()
        
        # 停止监控显示服务
        if hasattr(self, 'monitor_service') and self.monitor_service.is_running:
            await self.monitor_service.stop_monitoring()
        
        self.is_running = False
        self.logger.info("✅ 测试已停止")

async def main():
    """主函数"""
    parser = argparse.ArgumentParser(description='增强版市场监控压力测试')
    parser.add_argument('--hours', type=float, default=1.0,
                       help='测试时长（小时），默认1小时')
    parser.add_argument('--quick', action='store_true',
                       help='快速测试模式（5分钟）')
    parser.add_argument('--long', action='store_true',
                       help='长期测试模式（24小时）')
    parser.add_argument('--no-websocket', action='store_true',
                       help='不自动启动WebSocket服务器')
    parser.add_argument('--no-browser', action='store_true',
                       help='不自动打开浏览器')
    
    args = parser.parse_args()
    
    # 确定测试时长
    if args.long:
        duration = 24.0
    elif args.quick:
        duration = 5.0 / 60.0  # 5分钟
    else:
        duration = args.hours
    
    print(f"=== 开始 {duration} 小时压力测试 ===")
    print(f"📊 自动启动WebSocket服务器: {'是' if not args.no_websocket else '否'}")
    print("🌐 访问 http://localhost:8000 查看实时监控")
    print("按 Ctrl+C 停止测试\n")
    
    # 如果需要手动启动WebSocket服务器，给出提示
    if args.no_websocket:
        print("⚠️  注意：请确保已启动 WebSocket 服务器：")
        print("    $ cd src/market/monitor/backend")
        print("    $ python app.py 或 uvicorn app:app --host 0.0.0.0 --port 8000 --reload")
        print()
    
    # 创建并运行测试
    test = StressTest(
        duration_hours=duration,
        auto_start_websocket=not args.no_websocket
    )
    
    # 覆盖open_browser设置
    if args.no_browser:
        test.monitor_service.open_browser = False
    
    await test.run()

if __name__ == "__main__":
    asyncio.run(main())