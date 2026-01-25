// 在文件顶部导入配置文件
import adapterConfig from '../config/adapter.js';

// 导出Vue组件定义
export default {
    template: `
        <div class="container-fluid">
            <!-- 顶部导航栏 -->
            <nav class="navbar navbar-dark bg-dark mb-4">
                <div class="container-fluid">
                    <a class="navbar-brand" href="#">
                        <i class="bi bi-graph-up"></i> 市场数据实时监控
                    </a>
                    <div class="d-flex">
                        <span class="badge me-3" :class="connectionClass">
                            {{ connectionText }}
                        </span>
                        <span class="badge" :class="testStatusClass">
                            {{ testStatusText }}
                        </span>
                    </div>
                </div>
            </nav>

            <div class="row">
                <!-- 左侧信息面板 -->
                <div class="col-md-3">
                    <status-panel
                        :connected="connected"
                        :test-running="testRunning"
                        :elapsed-time="elapsedTime"
                        :start-time="startTime"
                        :total-data-points="totalDataPoints"
                        :last-update="lastUpdate"
                    />
                </div>

                <!-- 主内容区 -->
                <div class="col-md-9">
                    <!-- 实时数据概览 -->
                    <div class="row mb-4">
                        <div class="col-12">
                            <div class="card">
                                <div class="card-header">
                                    <h5 class="mb-0"><i class="bi bi-speedometer2"></i> 实时概览</h5>
                                </div>
                                <div class="card-body">
                                    <div class="row">
                                        <!-- 适配器卡片 -->
                                        <div v-for="(adapterData, adapterName) in adapters" 
                                             :key="adapterName"
                                             class="col-lg-6 col-md-12 mb-4">
                                            <adapter-card
                                                :adapter-name="adapterName"
                                                :adapter-data="adapterData"
                                                :config="getAdapterConfig(adapterName)"
                                                @toggle-collapse="toggleCollapse(adapterName)"
                                            />
                                        </div>
                                        
                                        <!-- 无数据提示 -->
                                        <div v-if="Object.keys(adapters).length === 0" class="col-12 text-center py-5">
                                            <div class="spinner-border text-primary" role="status"></div>
                                            <p class="mt-3">等待数据连接...</p>
                                            <small class="text-muted">适配器正在启动中...</small>
                                        </div>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>

                    <!-- 图表区域 -->
                    <div v-if="showCharts" class="row">
                        <div class="col-md-6">
                            <latency-chart
                                :chart-data="latencyData"
                                :title="'延迟趋势'"
                            />
                        </div>
                        
                        <div class="col-md-6">
                            <success-chart
                                :chart-data="successData"
                                :title="'成功率趋势'"
                            />
                        </div>
                    </div>

                    <!-- 详细数据表格 -->
                    <div v-if="showTable" class="card mt-4">
                        <div class="card-header">
                            <h5 class="mb-0"><i class="bi bi-table"></i> 详细指标</h5>
                        </div>
                        <div class="card-body">
                            <metrics-table :adapters="adapters" />
                        </div>
                    </div>
                </div>
            </div>
            
            <!-- 页脚 -->
            <footer class="mt-4 py-3 text-center text-muted">
                <small>市场数据监控系统 &copy; 2024 | 最后更新: {{ lastUpdate || '--' }}</small>
            </footer>
        </div>
    `,
    
    inject: ['websocket', 'notification'], // 移除 config 注入，因为我们现在直接导入配置
    
    data() {
        return {
            // 状态
            connected: false,
            testRunning: true,
            
            // 数据
            adapters: {},
            latencyData: {},  // 直接存储延迟数据
            successData: {},   // 直接存储成功率数据
            
            // 统计
            startTime: Date.now(),
            chartStartTime: null, // 图表开始时间（相对时间计算）
            totalDataPoints: 0,
            lastUpdate: null,
            elapsedTimer: null,
            collapseStates: {},
            
            // 使用导入的配置
            adapterConfig: adapterConfig
        };
    },
    
    computed: {
        connectionClass() {
            return this.connected ? 'bg-success' : 'bg-danger';
        },
        
        connectionText() {
            return this.connected ? '已连接' : '未连接';
        },
        
        testStatusClass() {
            return this.testRunning ? 'bg-success' : 'bg-secondary';
        },
        
        testStatusText() {
            return this.testRunning ? '运行中' : '已停止';
        },
        
        elapsedTime() {
            const seconds = Math.floor((Date.now() - this.startTime) / 1000);
            const hours = Math.floor(seconds / 3600);
            const minutes = Math.floor((seconds % 3600) / 60);
            const secs = seconds % 60;
            return `${hours.toString().padStart(2, '0')}:${minutes.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
        },
        
        showCharts() {
            // 如果没有注入的布局配置，默认显示图表
            return true;
        },
        
        showTable() {
            // 如果没有注入的布局配置，默认显示表格
            return true;
        }
    },
    
    methods: {
        getAdapterConfig(adapterName) {
            // 直接从导入的配置文件中获取配置
            const config = this.adapterConfig[adapterName];
            
            if (config) {
                return config;
            }
            
            // 如果没有找到配置，提供默认配置
            console.warn(`未找到适配器 ${adapterName} 的配置，使用默认配置`);
            return {
                name: adapterName.toUpperCase(),
                color: '#3b82f6',
                type: 'unknown',
                sections: [],
                metrics: {}
            };
        },
        
        toggleCollapse(adapterName) {
            this.collapseStates[adapterName] = !this.collapseStates[adapterName];
            
            // 保存到localStorage
            try {
                localStorage.setItem(`collapse_${adapterName}`, this.collapseStates[adapterName]);
            } catch (e) {
                console.warn('无法保存到本地存储:', e);
            }
        },
        
        // WebSocket消息处理
        handleWebSocketMessage(data) {
            this.totalDataPoints++;
            this.lastUpdate = new Date().toLocaleTimeString();
            
            console.log('📨 收到WebSocket消息:', data.type);
            
            switch (data.type) {
                case 'metrics_update':
                    console.log('📊 更新适配器数据:', data.data?.summary);
                    this.updateAdapters(data.data?.summary || {});
                    break;
                    
                case 'status':
                    this.testRunning = data.test_running !== false;
                    if (data.summary) {
                        console.log('📊 状态更新中包含摘要:', data.summary);
                        this.updateAdapters(data.summary);
                    }
                    break;
                    
                case 'initial_data':
                    console.log('📊 初始数据:', data);
                    if (data.start_time) {
                        this.startTime = new Date(data.start_time).getTime();
                    }
                    if (data.summary) {
                        this.updateAdapters(data.summary);
                    }
                    break;
                    
                case 'test_complete':
                    this.testRunning = false;
                    this.notification?.show('测试完成', data.message || '测试已完成', 'success');
                    break;
                    
                case 'summary':
                    console.log('📊 摘要更新:', data.summary);
                    if (data.summary) {
                        this.updateAdapters(data.summary);
                    }
                    break;
            }
        },
        
        updateAdapters(summary) {
            console.log('🔄 更新适配器, 数量:', Object.keys(summary || {}).length);
            
            Object.entries(summary || {}).forEach(([adapter, metrics]) => {
                console.log(`🔍 ${adapter} 完整指标:`, metrics);
                
                // 特别检查信号统计字段
                if (adapter === 'binance') {
                    console.log(`📊 ${adapter} 信号统计字段检查:`);
                    console.log('  total_signals:', metrics.total_signals);
                    console.log('  t0_rate:', metrics.t0_rate);
                    console.log('  avg_signals_per_minute:', metrics.avg_signals_per_minute);
                    console.log('  recent_signals_per_minute:', metrics.recent_signals_per_minute);
                    console.log('  validations_total:', metrics.validations_total);
                    console.log('  validations_success:', metrics.validations_success);
                }
                
                // 更新适配器数据
                this.adapters[adapter] = {
                    ...this.adapters[adapter],
                    ...metrics,
                    lastUpdate: new Date().toLocaleTimeString()
                };
                
                // 更新图表数据
                this.updateChartData(adapter, metrics);
            });
        },
        
        updateChartData(adapter, metrics) {
            // 初始化图表开始时间
            if (!this.chartStartTime) {
                this.chartStartTime = Date.now() / 1000;
                console.log('⏰ 图表开始时间:', this.chartStartTime);
            }
            
            const now = Date.now() / 1000;
            const elapsedSeconds = now - this.chartStartTime;
            
            console.log(`📈 ${adapter}: 时间=${elapsedSeconds.toFixed(1)}s, 延迟=${metrics.avg_latency_ms}ms`);
            
            // 初始化延迟数据
            if (!this.latencyData[adapter]) {
                this.latencyData[adapter] = [];
            }
            
            // 初始化成功率数据
            if (!this.successData[adapter]) {
                this.successData[adapter] = [];
            }
            
            // 添加新数据点 - 确保格式正确
            const latencyPoint = {
                x: elapsedSeconds,
                y: metrics.avg_latency_ms || 0
            };
            
            const successPoint = {
                x: elapsedSeconds,
                y: (metrics.success_rate || 0) * 100
            };
            
            this.latencyData[adapter].push(latencyPoint);
            this.successData[adapter].push(successPoint);
            
            // 保持最近100个数据点
            const maxPoints = 100;
            if (this.latencyData[adapter].length > maxPoints) {
                this.latencyData[adapter].shift();
            }
            if (this.successData[adapter].length > maxPoints) {
                this.successData[adapter].shift();
            }
            
            // 强制响应式更新 - 创建新对象引用
            this.latencyData = { ...this.latencyData };
            this.successData = { ...this.successData };
            
            // 调试：查看数据
            console.log(`📊 ${adapter} 延迟数据:`, this.latencyData[adapter]);
        },
        
        markAdaptersOffline() {
            Object.keys(this.adapters).forEach(adapter => {
                if (this.adapters[adapter]) {
                    this.adapters[adapter].is_connected = false;
                }
            });
        }
    },
    
    mounted() {
        console.log('🚀 父组件挂载');
        
        // 连接WebSocket
        this.websocket.connect();
        
        // 监听WebSocket事件
        this.websocket.on('connected', () => {
            this.connected = true;
            console.log('✅ WebSocket 已连接');
        });
        
        this.websocket.on('disconnected', () => {
            this.connected = false;
            this.testRunning = false;
            this.markAdaptersOffline();
            console.log('❌ WebSocket 断开连接');
        });
        
        this.websocket.on('message', this.handleWebSocketMessage);
        
        // 启动运行时间计时器
        this.elapsedTimer = setInterval(() => {
            // 触发计算属性更新
            this.$forceUpdate();
        }, 1000);
        
        // 加载折叠状态
        Object.keys(this.adapterConfig).forEach(adapter => {
            try {
                const storedState = localStorage.getItem(`collapse_${adapter}`);
                if (storedState !== null) {
                    this.collapseStates[adapter] = storedState === 'true';
                }
            } catch (e) {
                console.warn('无法从本地存储读取:', e);
            }
        });
    },
    
    beforeUnmount() {
        console.log('🗑️ 父组件卸载');
        
        // 清理计时器
        if (this.elapsedTimer) {
            clearInterval(this.elapsedTimer);
        }
        
        // 移除WebSocket监听
        this.websocket.off('message', this.handleWebSocketMessage);
        this.websocket.disconnect();
    }
};