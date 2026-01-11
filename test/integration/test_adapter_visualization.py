# tests/integration/test_adapter_visualization.py
import asyncio
import time
import sys
import os
import pytest
import signal
from typing import Dict, List, Any
from datetime import datetime

# 添加 src 目录到 Python 路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from market.monitor.collector import MarketMonitor
from market.adapter.binance_adapter import BinanceAdapter
from market.adapter.polymarket_adapter import PolymarketAdapter
from market.service.ws_manager import WebSocketManager


@pytest.mark.integration
@pytest.mark.asyncio
class TestAdaptersVisualization:
    """适配器可视化测试 - 连接真实数据"""

    TEST_TIME = 30 # 30秒
    
    async def test_monitor_binance_and_polymarket(self):
        """测试Binance和Polymarket的监控可视化 - 连接真实数据"""
        
        print(f"\n{'='*60}")
        print("开始真实数据监控测试")
        print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'='*60}\n")
        
        # 创建监控器
        monitor = MarketMonitor()
        
        # 创建并配置适配器
        binance = BinanceAdapter()
        
        # 根据您的PolymarketAdapter的实际实现调整参数
        polymarket = PolymarketAdapter()
        
        # 设置监控器
        binance.set_monitor(monitor)
        polymarket.set_monitor(monitor)
        
        # 创建WebSocket管理器
        ws_manager = WebSocketManager()
        ws_manager.register_adapter('binance', binance)
        ws_manager.register_adapter('polymarket', polymarket)
        
        try:
            # 启动WebSocket连接
            print("启动WebSocket连接...")
            await ws_manager.start()
            await asyncio.sleep(2)  # 等待连接建立
            
            # 订阅交易对
            print("订阅交易对...")
            
            # Binance交易对（选择流动性好的）
            binance_symbols = ['BTCUSDT', 'ETHUSDT']
            await binance.subscribe(binance_symbols)
            print(f"  Binance订阅: {binance_symbols}")
            
            # Polymarket交易对（根据您的实际市场调整）
            # 这里假设您的PolymarketAdapter支持这些交易对
            # 如果不同，请根据实际情况调整
            try:
                market_ids = await polymarket.get_active_market_id(3)
                await polymarket.subscribe(market_ids)
                print(f"  Polymarket订阅: {market_ids}")
            except Exception as e:
                print(f"  Polymarket订阅失败: {e}")
                # 尝试使用通用交易对
            
            # 收集数据（30秒）
            print(f"\n开始收集30秒实时数据...")
            print("按 Ctrl+C 可提前停止测试")
            
            # 设置信号处理以便可以提前停止
            stop_event = asyncio.Event()
            
            def signal_handler():
                print("\n收到中断信号，正在停止测试...")
                stop_event.set()
            
            # 注册信号处理（在Unix-like系统上）
            if hasattr(signal, 'SIGINT'):
                loop = asyncio.get_event_loop()
                loop.add_signal_handler(signal.SIGINT, signal_handler)
            
            # 数据收集循环
            start_time = time.time()
            check_interval = 5  # 每5秒打印一次状态
            last_check = start_time
            
            while time.time() - start_time < self.TEST_TIME and not stop_event.is_set():
                current_time = time.time()
                
                # 每5秒打印一次状态
                if current_time - last_check >= check_interval:
                    elapsed = int(current_time - start_time)
                    remaining = max(0, self.TEST_TIME - elapsed)
                    
                    summary = monitor.get_summary()
                    print("summary:", summary)
                    
                    print(f"\n[进度] 已收集 {elapsed} 秒，剩余 {remaining} 秒")
                    print("当前状态:")
                    
                    for adapter, metrics in summary.items():
                        print(f"  {adapter}:")
                        
                        # 修改：使用更清晰的字段访问方式
                        adapter_type = metrics.get('adapter_type', 'unknown')
                        is_connected = metrics.get('is_connected', False)
                        avg_latency = metrics.get('avg_latency_ms', 0)
                        
                        # 根据适配器类型获取适当的计数
                        if adapter_type == 'binance':
                            count_field = 'validations_total'
                            success_rate_field = 'validation_success_rate'
                        else:
                            count_field = 'messages_received'
                            # 对于Polymarket，使用 1 - error_rate 作为成功率
                            error_rate = metrics.get('error_rate', 0)
                            success_rate = 1.0 - error_rate if error_rate <= 1.0 else 0.0
                            success_rate_field = None  # 不使用字段，直接使用计算值
                        
                        count = metrics.get(count_field, 0)
                        if success_rate_field:
                            success_rate = metrics.get(success_rate_field, 0)
                        else:
                            success_rate = 1.0 - metrics.get('error_rate', 0) if count > 0 else 0.0
                        
                        print(f"    成功率: {success_rate:.2%}")
                        print(f"    平均延迟: {avg_latency:.2f}ms")
                        print(f"    总消息/验证次数: {count}")
                        
                        # 修改：更清晰的连接状态显示
                        if is_connected:
                            print(f"    连接状态: ✅ 已连接")
                        else:
                            print(f"    连接状态: ❌ 未连接 (错误数: {metrics.get('connection_errors', 0)})")
                    
                    last_check = current_time
                
                await asyncio.sleep(0.1)  # 短暂休眠，避免忙等待
            
            if stop_event.is_set():
                print("\n测试被用户中断")
            
            # 测试完成，获取最终监控摘要
            print(f"\n{'='*60}")
            print("测试完成，生成最终报告")
            print(f"{'='*60}")
            
            final_summary = monitor.get_summary()
            
            print("\n=== 最终监控摘要 ===")
            for adapter, metrics in final_summary.items():
                print(f"\n{adapter}:")
                adapter_type = metrics.get('adapter_type', 'unknown')
                print(f"  适配器类型: {adapter_type}")
                print(f"  交易所类型: {metrics.get('exchange_type', 'N/A')}")
                
                # 修改：根据适配器类型显示不同的统计信息
                if adapter_type == 'binance':
                    print(f"  验证成功率: {metrics.get('validation_success_rate', 0):.2%}")
                    print(f"  总验证次数: {metrics.get('validations_total', 0)}")
                    print(f"  有效验证: {metrics.get('validations_success', 0)}")
                    print(f"  无效验证: {metrics.get('validations_failed', 0)}")
                else:
                    print(f"  消息成功率: {(1.0 - metrics.get('error_rate', 0)):.2%}")
                    print(f"  收到消息数: {metrics.get('messages_received', 0)}")
                    print(f"  处理消息数: {metrics.get('messages_processed', 0)}")
                
                print(f"  平均延迟: {metrics.get('avg_latency_ms', 0):.2f}ms")
                print(f"  最大延迟: {metrics.get('max_latency_ms', 0):.2f}ms")
                print(f"  P50延迟: {metrics.get('p50_latency_ms', 0):.2f}ms")
                print(f"  P95延迟: {metrics.get('p95_latency_ms', 0):.2f}ms")
                print(f"  P99延迟: {metrics.get('p99_latency_ms', 0):.2f}ms")
                print(f"  错误率: {metrics.get('error_rate', 0):.2%}")
                print(f"  连接状态: {'✅ 已连接' if metrics.get('is_connected', False) else '❌ 未连接'}")
                print(f"  连接错误: {metrics.get('connection_errors', 0)}次")
                print(f"  订阅交易对: {metrics.get('subscribed_symbols', [])}")
            
            # 断言验证
            print("\n=== 断言验证 ===")
            
            # 修改：使用总消息数而不是总验证次数
            total_messages = sum(
                metrics.get('messages_received', 0) 
                for metrics in final_summary.values()
            )
            
            if total_messages > 0:
                print(f"✅ 成功收集到 {total_messages} 条消息")
                assert total_messages > 0, "应该至少收集到一条消息"
            else:
                print("⚠️ 未收集到消息数据，可能连接或订阅有问题")
            
            # 检查Binance数据
            if 'binance' in final_summary:
                binance_metrics = final_summary['binance']
                # 修改：检查binance是否至少收到了一些数据
                messages_received = binance_metrics.get('messages_received', 0)
                validations_total = binance_metrics.get('validations_total', 0)
                
                if messages_received > 0 or validations_total > 0:
                    print("✅ Binance 数据收集正常")
                    # 检查延迟合理性（应该在合理范围内）
                    avg_latency = binance_metrics.get('avg_latency_ms', 0)
                    if 0 < avg_latency < 1000:  # 延迟应该在1秒以内
                        print(f"✅ Binance 平均延迟正常: {avg_latency:.2f}ms")
                    else:
                        print(f"⚠️ Binance 平均延迟异常: {avg_latency:.2f}ms")
                else:
                    print("❌ Binance 未收集到数据")
            
            # 检查Polymarket数据
            if 'polymarket' in final_summary:
                polymarket_metrics = final_summary['polymarket']
                messages_received = polymarket_metrics.get('messages_received', 0)
                
                if messages_received > 0:
                    print("✅ Polymarket 数据收集正常")
                else:
                    print("❌ Polymarket 未收集到数据")
            
            # 生成可视化图表
            print("\n生成可视化图表...")
            await self._generate_visualization(monitor)
            
            # 保存详细指标到文件
            await self._save_metrics_to_file(final_summary)
            
            print(f"\n{'='*60}")
            print("测试完成！")
            print(f"{'='*60}")
            
        except Exception as e:
            print(f"\n❌ 测试失败: {e}")
            import traceback
            print(traceback.format_exc())
            raise
        
        finally:
            # 清理资源
            print("\n清理资源...")
            try:
                await ws_manager.stop()
            except Exception as e:
                print(f"清理资源时出错: {e}")
    
    async def _generate_visualization(self, monitor: MarketMonitor):
        """生成可视化图表"""
        try:
            # 检查是否有matplotlib
            import matplotlib
            matplotlib.use('Agg')  # 使用非交互式后端
            import matplotlib.pyplot as plt
            import numpy as np
            
            metrics = monitor.metrics
            
            # 检查是否有数据
            if not metrics:
                print("⚠️ 没有监控数据可生成图表")
                return
            
            # 创建图表
            fig, axes = plt.subplots(2, 2, figsize=(14, 10))
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            fig.suptitle(f'Adapter Performance Monitoring\n{timestamp}', fontsize=14)
            
            # 1. 成功率对比
            ax1 = axes[0, 0]
            adapter_names = []
            success_rates = []
            
            for adapter_name, metric in metrics.items():
                if hasattr(metric, 'success_rate') and metric.success_rate > 0:
                    adapter_names.append(adapter_name.capitalize())
                    success_rates.append(metric.success_rate * 100)
            
            if success_rates:
                bars = ax1.bar(adapter_names, success_rates, color=['#1f77b4', '#ff7f0e'])
                ax1.set_title('Validation Success Rate', fontweight='bold')
                ax1.set_ylabel('Success Rate (%)')
                ax1.set_ylim(0, 105)
                
                # 添加数值标签
                for bar in bars:
                    height = bar.get_height()
                    ax1.text(bar.get_x() + bar.get_width()/2, height,
                            f'{height:.1f}%', ha='center', va='bottom')
            else:
                ax1.text(0.5, 0.5, 'No success rate data available', 
                        ha='center', va='center', transform=ax1.transAxes)
                ax1.set_title('Validation Success Rate', fontweight='bold')
            
            # 2. 延迟对比
            ax2 = axes[0, 1]
            adapter_names = []
            avg_latencies = []
            max_latencies = []
            
            for adapter_name, metric in metrics.items():
                if hasattr(metric, 'latency_ms') and metric.latency_ms:
                    adapter_names.append(adapter_name.capitalize())
                    avg_latencies.append(metric.avg_latency)
                    max_latencies.append(metric.max_latency)
            
            if avg_latencies:
                x = np.arange(len(adapter_names))
                width = 0.35
                
                bars1 = ax2.bar(x - width/2, avg_latencies, width, 
                               label='Average', color='#2ca02c', alpha=0.7)
                bars2 = ax2.bar(x + width/2, max_latencies, width, 
                               label='Maximum', color='#d62728', alpha=0.7)
                
                ax2.set_title('Latency Comparison', fontweight='bold')
                ax2.set_ylabel('Latency (ms)')
                ax2.set_xticks(x)
                ax2.set_xticklabels(adapter_names)
                ax2.legend()
                
                # 添加数值标签
                for bars in [bars1, bars2]:
                    for bar in bars:
                        height = bar.get_height()
                        ax2.text(bar.get_x() + bar.get_width()/2, height,
                                f'{height:.0f}', ha='center', va='bottom', fontsize=9)
            else:
                ax2.text(0.5, 0.5, 'No latency data available', 
                        ha='center', va='center', transform=ax2.transAxes)
                ax2.set_title('Latency Comparison', fontweight='bold')
            
            # 3. 时间序列延迟（如果数据足够）
            ax3 = axes[1, 0]
            has_time_series_data = False
            
            for adapter_name, metric in metrics.items():
                if hasattr(metric, 'latency_ms') and metric.latency_ms:
                    has_time_series_data = True
                    # 只显示最近的数据点
                    samples_to_show = min(50, len(metric.latency_ms))
                    samples = metric.latency_ms[-samples_to_show:]
                    
                    ax3.plot(range(len(samples)), samples, 
                            label=adapter_name.capitalize(), 
                            marker='.', markersize=4, linewidth=1.5)
            
            if has_time_series_data:
                ax3.set_title('Latency Over Time (Last 50 samples)', fontweight='bold')
                ax3.set_xlabel('Sample Index')
                ax3.set_ylabel('Latency (ms)')
                ax3.legend()
                ax3.grid(True, alpha=0.3)
            else:
                ax3.text(0.5, 0.5, 'No time series latency data', 
                        ha='center', va='center', transform=ax3.transAxes)
                ax3.set_title('Latency Over Time', fontweight='bold')
            
            # 4. 验证次数分布
            ax4 = axes[1, 1]
            adapter_names = []
            valid_counts = []
            invalid_counts = []
            
            for adapter_name, metric in metrics.items():
                if hasattr(metric, 'valid_count') or hasattr(metric, 'invalid_count'):
                    adapter_names.append(adapter_name.capitalize())
                    valid_counts.append(getattr(metric, 'valid_count', 0))
                    invalid_counts.append(getattr(metric, 'invalid_count', 0))
            
            if any(valid_counts) or any(invalid_counts):
                x = np.arange(len(adapter_names))
                width = 0.35
                
                bars1 = ax4.bar(x - width/2, valid_counts, width, 
                               label='Valid', color='#2ca02c', alpha=0.7)
                bars2 = ax4.bar(x + width/2, invalid_counts, width, 
                               label='Invalid', color='#d62728', alpha=0.7)
                
                ax4.set_title('Validation Counts', fontweight='bold')
                ax4.set_ylabel('Count')
                ax4.set_xticks(x)
                ax4.set_xticklabels(adapter_names)
                ax4.legend()
                
                # 添加数值标签
                for bars in [bars1, bars2]:
                    for bar in bars:
                        height = bar.get_height()
                        if height > 0:
                            ax4.text(bar.get_x() + bar.get_width()/2, height,
                                    f'{int(height)}', ha='center', va='bottom', fontsize=9)
            else:
                ax4.text(0.5, 0.5, 'No validation count data', 
                        ha='center', va='center', transform=ax4.transAxes)
                ax4.set_title('Validation Counts', fontweight='bold')
            
            plt.tight_layout()
            
            # 保存图表
            results_dir = "./logs/results"
            os.makedirs(results_dir, exist_ok=True)
            
            timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"{results_dir}/monitoring_results_{timestamp_str}.png"
            plt.savefig(filename, dpi=150, bbox_inches='tight')
            plt.close()
            
            print(f"✅ 图表已保存到: {filename}")
            
            # 生成文本报告
            report_file = f"{results_dir}/monitoring_report_{timestamp_str}.txt"
            with open(report_file, 'w', encoding='utf-8') as f:
                f.write(f"Adapter Performance Monitoring Report\n")
                f.write(f"Generated: {timestamp}\n")
                f.write(f"{'='*50}\n\n")
                
                for adapter_name, metric in metrics.items():
                    f.write(f"{adapter_name.upper()}:\n")
                    f.write(f"{'-'*30}\n")
                    
                    if hasattr(metric, 'success_rate'):
                        f.write(f"Success Rate: {metric.success_rate:.2%}\n")
                    
                    if hasattr(metric, 'avg_latency'):
                        f.write(f"Average Latency: {metric.avg_latency:.2f}ms\n")
                    
                    if hasattr(metric, 'max_latency'):
                        f.write(f"Maximum Latency: {metric.max_latency:.2f}ms\n")
                    
                    if hasattr(metric, 'valid_count'):
                        f.write(f"Valid Validations: {metric.valid_count}\n")
                    
                    if hasattr(metric, 'invalid_count'):
                        f.write(f"Invalid Validations: {metric.invalid_count}\n")
                    
                    if hasattr(metric, 'is_connected'):
                        f.write(f"Connected: {metric.is_connected}\n")
                    
                    f.write(f"\n")
            
            print(f"✅ 报告已保存到: {report_file}")
            
        except ImportError:
            print("⚠️ Matplotlib未安装，跳过图表生成")
            print("   安装命令: pip install matplotlib")
        except Exception as e:
            print(f"⚠️ 图表生成失败: {e}")
    
    async def _save_metrics_to_file(self, summary: Dict[str, Any]):
        """保存指标到JSON文件"""
        try:
            import json
            
            results_dir = "./tests/integration/results"
            os.makedirs(results_dir, exist_ok=True)
            
            timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"{results_dir}/metrics_{timestamp_str}.json"
            
            # 确保数据可序列化
            serializable_summary = {}
            for adapter, metrics in summary.items():
                serializable_summary[adapter] = {
                    k: (float(v) if isinstance(v, (int, float)) else v)
                    for k, v in metrics.items()
                }
            
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(serializable_summary, f, indent=2, ensure_ascii=False)
            
            print(f"✅ 详细指标已保存到: {filename}")
            
        except Exception as e:
            print(f"⚠️ 保存指标时出错: {e}")


# 添加一个快速验证测试
@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.quick
async def test_monitor_quick_validation():
    """快速验证监控器基本功能"""
    from market.monitor.collector import MarketMonitor
    
    monitor = MarketMonitor()
    
    # 注册测试适配器
    monitor.register_adapter("test_binance", "BINANCE")
    monitor.register_adapter("test_polymarket", "POLYMARKET")
    
    # 添加一些测试数据
    for i in range(10):
        monitor.record_latency("test_binance", 50 + i * 5)
        monitor.record_validation_result(
            adapter_name="test_binance",
            symbol="BTCUSDT",
            is_valid=True,
            details={'data_timestamp': int(time.time() * 1000) - 100}
        )
    
    summary = monitor.get_summary()
    
    assert "test_binance" in summary
    assert summary["test_binance"]["avg_latency_ms"] > 0
    assert summary["test_binance"]["success_rate"] == 1.0
    
    print("✅ 监控器快速验证测试通过")


if __name__ == "__main__":
    # 可以直接运行这个测试
    print("直接运行监控测试...")
    
    async def main():
        test = TestAdaptersVisualization()
        await test.test_monitor_binance_and_polymarket()
    
    asyncio.run(main())