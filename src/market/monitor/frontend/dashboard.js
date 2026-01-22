// 在文件开头添加
console.log('Dashboard.js 开始加载...');

// 检查必要的全局依赖
function checkDependencies() {
    console.log('检查依赖...');
    
    const missingDeps = [];
    
    // 检查Chart.js
    if (typeof Chart === 'undefined') {
        console.error('❌ Chart.js 未加载');
        missingDeps.push('Chart.js');
    } else {
        console.log('✅ Chart.js 已加载');
    }
    
    // 检查Bootstrap
    if (typeof bootstrap === 'undefined') {
        console.warn('⚠️  Bootstrap 未加载（某些功能可能受限）');
    } else {
        console.log('✅ Bootstrap 已加载');
    }
    
    if (missingDeps.length > 0) {
        console.error('缺少依赖:', missingDeps.join(', '));
        return false;
    }
    
    return true;
}

class MarketDashboard {
    constructor() {
        console.log('创建MarketDashboard实例...');
        
        this.ws = null;
        this.charts = {};
        this.dataHistory = {};
        this.connected = false;
        this.testRunning = true; // 默认为运行中，因为MonitorService会自动启动
        this.startTime = Date.now();
        this.totalDataPoints = 0;
        
        this.initCharts();
        this.bindEvents();
        this.connectWebSocket(); // 自动连接
        this.updateStatus();
        this.startElapsedTimer(); // 启动运行时间计时器

        // 添加折叠状态管理
        this.collapseStates = {
            'binance': true, // 默认展开
            'polymarket': true
        };
        
        // 绑定事件处理方法
        this._handleToggleClick = this._handleToggleClick.bind(this);
    }
    
    initCharts() {
        console.log('初始化图表...');
        
        try {
            // 延迟图表
            const latencyCtx = document.getElementById('latency-chart');
            if (!latencyCtx) {
                console.error('❌ 找不到 #latency-chart 元素');
                return;
            }
            
            // 移除 chartjs-plugin-streaming 配置，使用标准时间轴
            this.charts.latency = new Chart(latencyCtx.getContext('2d'), {
                type: 'line',
                data: {
                    datasets: []
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    scales: {
                        x: {
                            type: 'linear',
                            position: 'bottom',
                            title: {
                                display: true,
                                text: '时间（秒）'
                            },
                            ticks: {
                                callback: function(value) {
                                    // 将时间戳转换为相对时间
                                    return value.toFixed(0) + 's';
                                }
                            }
                        },
                        y: {
                            beginAtZero: true,
                            title: {
                                display: true,
                                text: '延迟 (ms)'
                            }
                        }
                    },
                    plugins: {
                        legend: {
                            display: true,
                            position: 'top'
                        },
                        tooltip: {
                            mode: 'index',
                            intersect: false,
                            callbacks: {
                                label: function(context) {
                                    return `${context.dataset.label}: ${context.parsed.y.toFixed(1)}ms`;
                                }
                            }
                        }
                    },
                    interaction: {
                        intersect: false,
                        mode: 'nearest'
                    },
                    animation: {
                        duration: 0 // 禁用动画以获得更好的性能
                    }
                }
            });
            
            // 成功率图表
            const successCtx = document.getElementById('success-rate-chart');
            if (!successCtx) {
                console.error('❌ 找不到 #success-rate-chart 元素');
                return;
            }
            
            this.charts.success = new Chart(successCtx.getContext('2d'), {
                type: 'line',
                data: {
                    datasets: []
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    scales: {
                        x: {
                            type: 'linear',
                            position: 'bottom',
                            title: {
                                display: true,
                                text: '时间（秒）'
                            },
                            ticks: {
                                callback: function(value) {
                                    return value.toFixed(0) + 's';
                                }
                            }
                        },
                        y: {
                            min: 0,
                            max: 100,
                            title: {
                                display: true,
                                text: '成功率 (%)'
                            }
                        }
                    },
                    plugins: {
                        legend: {
                            display: true,
                            position: 'top'
                        },
                        tooltip: {
                            mode: 'index',
                            intersect: false,
                            callbacks: {
                                label: function(context) {
                                    return `${context.dataset.label}: ${context.parsed.y.toFixed(1)}%`;
                                }
                            }
                        }
                    },
                    interaction: {
                        intersect: false,
                        mode: 'nearest'
                    },
                    animation: {
                        duration: 0
                    }
                }
            });
            
            console.log('✅ 图表初始化完成');
        } catch (error) {
            console.error('❌ 图表初始化失败:', error);
        }
    }
    
    bindEvents() {
        console.log('绑定事件监听器...');
        
        // 检查新元素是否存在
        const requiredElements = [
            'connection-status', 'test-status',
            'latency-chart', 'success-rate-chart',
            'overview-cards', 'metrics-body',
            'adapter-status-list', 'test-stats'
        ];
        
        console.log('检查DOM元素:');
        requiredElements.forEach(id => {
            const element = document.getElementById(id);
            console.log(`  #${id}:`, element ? '✅ 存在' : '❌ 不存在');
        });
        
        // 测试按钮点击（用于调试）
        document.body.addEventListener('click', (e) => {
            console.log('页面点击:', {
                target: e.target.id || e.target.className || e.target.tagName,
                timestamp: new Date().toISOString()
            });
        }, { capture: true });
        
        console.log('事件绑定完成');
    }
    
    connectWebSocket() {
        console.log('自动连接WebSocket...');
        
        // 如果已有连接，先关闭
        if (this.ws) {
            this.ws.close();
        }
        
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = `${protocol}//${window.location.host}/ws`;
        
        console.log(`正在连接WebSocket: ${wsUrl}`);
        
        this.ws = new WebSocket(wsUrl);
        
        this.ws.onopen = () => {
            console.log('✅ WebSocket连接已建立');
            this.connected = true;
            this.updateStatus();
            
            // 连接成功后请求初始数据
            setTimeout(() => {
                this.requestInitialData();
            }, 1000);
        };
        
        this.ws.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                console.log('📨 收到WebSocket消息:', data.type);
                this.handleMessage(data);
            } catch (error) {
                console.error('解析消息失败:', error);
            }
        };
        
        this.ws.onclose = (event) => {
            console.log('WebSocket连接已关闭', {
                code: event.code,
                reason: event.reason,
                wasClean: event.wasClean
            });
            
            this.connected = false;
            
            // 连接关闭时，认为测试已停止
            this.testRunning = false;
            
            // 停止运行时间计时器
            if (this.elapsedTimer) {
                clearInterval(this.elapsedTimer);
                this.elapsedTimer = null;
            }

            // 更新适配器为离线状态
            this.updateAdaptersToOffline();
            
            this.updateStatus();
            
            // 显示连接断开通知
            this.showNotification(
                '连接断开', 
                '与服务器的WebSocket连接已断开，监控已停止',
                'warning'
            );
            
            // 3秒后尝试重连
            setTimeout(() => {
                console.log('尝试重新连接...');
                this.connectWebSocket();
            }, 3000);
        };
        
        this.ws.onerror = (error) => {
            console.error('WebSocket错误:', error);
        };
    }
    
    requestInitialData() {
        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
            console.log('请求初始数据...');
            this.ws.send(JSON.stringify({ 
                type: 'get_initial_data' 
            }));
        } else {
            // 如果WebSocket未就绪，通过HTTP获取数据
            this.fetchDataViaHTTP();
        }
    }
    
    handleMessage(data) {
        this.totalDataPoints++;
        
        // 更新最后更新时间显示
        const lastUpdateEl = document.getElementById('last-update');
        if (lastUpdateEl) {
            lastUpdateEl.textContent = new Date().toLocaleTimeString();
        }
        
        // 更新数据点计数
        const dataPointsEl = document.getElementById('total-data-points');
        if (dataPointsEl) {
            dataPointsEl.textContent = this.totalDataPoints.toLocaleString();
        }
        
        switch (data.type) {
            case 'metrics_update':
                this.updateDashboard(data.data);
                break;
                
            case 'status':
                this.testRunning = data.test_running !== false; // 默认为true
                if (data.summary) {
                    this.updateDashboard({ summary: data.summary });
                }
                this.updateStatus();
                break;
                
            case 'initial_data':
                // 处理初始数据
                if (data.start_time) {
                    this.updateStartTime(data.start_time);
                }
                if (data.summary) {
                    this.updateDashboard({ summary: data.summary });
                }
                break;
                
            case 'test_complete':
                this.testRunning = false;
                this.showNotification('测试完成', data.message || '测试已完成', 'success');
                this.updateStatus();
                break;
                
            case 'summary':
                if (data.summary) {
                    this.updateDashboard({ summary: data.summary });
                }
                break;
        }
    }
    
    updateDashboard(data) {
        const summary = data.summary || {};
        const testInfo = data.test_info || {};
        
        console.log('更新仪表板数据，适配器数量:', Object.keys(summary).length);
        
        // 更新概览卡片
        this.updateOverviewCards(summary);
        
        // 更新表格
        this.updateMetricsTable(summary);
        
        // 更新图表
        this.updateCharts(summary);
        
        // 更新统计信息
        this.updateStats(testInfo);
    }
    
    updateOverviewCards(summary) {
        const container = document.getElementById('overview-cards');
        if (!container) {
            console.error('❌ 找不到 #overview-cards 容器');
            return;
        }
        
        container.innerHTML = '';
        
        Object.entries(summary).forEach(([adapter, metrics], index) => {
            const latency = metrics.avg_latency_ms || 0;
            const successRate = (metrics.success_rate || 0) * 100;
            const messages = metrics.messages_received || 0;
            const isConnected = metrics.is_connected || false;
            
            // 延迟状态颜色
            let latencyColor = 'danger';
            if (latency < 50) latencyColor = 'success';
            else if (latency < 100) latencyColor = 'warning';
            
            // 连接状态
            const connectionIcon = isConnected ? 
                '<i class="bi bi-check-circle-fill text-success"></i>' : 
                '<i class="bi bi-x-circle-fill text-danger"></i>';
            
            // 获取订阅列表
            const subscribedSymbols = metrics.subscribed_symbols || [];
            const subscribedCount = subscribedSymbols.length;
            
            let commonMetrics = '';
            let specificMetrics = '';
            
            // Binance 指标
            if (adapter === 'binance' || metrics.adapter_type === 'binance') {
                /*
                {
                    'adapter_type': 'binance',
                    'is_connected': True,
                    'connection_errors': 0,
                    'avg_latency_ms': 1.4641418175194065,
                    'max_latency_ms': 3960,
                    'p50_latency_ms': 6,
                    'p95_latency_ms': 418,
                    'p99_latency_ms': 650,
                    'error_rate': 0.0,
                    'messages_received': 2177,
                    'messages_processed': 2177,
                    'errors': 0,
                    'subscribed_symbols': ['ETHUSDT', 'BTCUSDT'],
                    'success_rate': 1.0,
                    'validation_success_rate': 1.0,
                    'avg_pending_buffer': 0.0,
                    'validations_total': 6,
                    'validations_success': 6,
                    'validations_failed': 0,
                    'warnings': 26,
                    'total_signals': 2,
                    't0_rate': 0.001084010840108401,
                    'false_positive_rate': 0.0,
                    'avg_signals_per_minute': 5.8397002287215924,
                    'avg_signal_interval': 2177,
                    'avg_cooldown_interval': 17.545454545454547,
                    'up_percent': 1.0,
                    'down_percent': 0.0,
                    'recent_signals_per_minute': 2.0,
                    'recent_transitions_per_minute': 4.0,
                    'recent_signal_interval': 2177,
                    'recent_up_percent': 1.0,
                    'recent_down_percent': 0.0
                }
                */
                const tradeCount = metrics.trade_count || 0;
                const depthUpdateCount = metrics.depthUpdate_count || 0;
                const validations = metrics.validations_total || 0;
                const validationsSuccess = metrics.validations_success || 0;
                const validationSuccessRate = (metrics.validation_success_rate || 0) * 100;
                const warnings = metrics.warnings || 0;
                const avgPendingBuffer = metrics.avg_pending_buffer || 0;

                // T0信息
                // 整体统计 
                const t0Count = metrics.total_signals || 0;
                const t0Rate = (metrics.t0_rate || 0) * 100;
                const falsePositiveRate = (metrics.false_positive_rate || 0) * 100;
                const t0AvgPerMinute = metrics.avg_signals_per_minute || 0;
                const avgSignalInterval = metrics.avg_signal_interval || 0;
                const avgCooldownInterval = metrics.avg_cooldown_interval || 0;
                const upPercent = (metrics.up_percent || 0) * 100;
                const downPercent = (metrics.down_percent || 0) * 100;
                // 最近1分钟统计
                const t0RecentPerMinute = metrics.recent_signals_per_minute || 0;
                const recentTransitionsPerMinute = metrics.recent_transitions_per_minute || 0;
                const recentSignalInterval = metrics.recent_signal_interval || 0;
                const recentUpPercent = (metrics.recent_up_percent || 0) * 100;
                const recentDownPercent = (metrics.recent_down_percent || 0) * 100;
                
                
                // 消息数详情
                const messagesDetails = `
                    <div class="mt-1">
                        <small class="text-muted d-block mb-1">消息详情：</small>
                        <div class="d-flex justify-content-center">
                            <span class="badge bg-info me-1">交易: ${tradeCount}</span>
                            <span class="badge bg-primary">深度: ${depthUpdateCount}</span>
                        </div>
                    </div>
                `;
                
                // 通用指标
                commonMetrics = `
                    <div class="row mb-3">
                        <div class="col-6 text-center">
                            <h5 class="mb-1">${successRate.toFixed(1)}%</h5>
                            <small class="text-muted">成功率</small>
                        </div>
                        <div class="col-6 text-center">
                            <h5 class="mb-1">${messages}</h5>
                            <small class="text-muted">总消息数</small>
                            ${messagesDetails}
                        </div>
                    </div>
                `;
                
                // Binance 详细指标
                specificMetrics = `
                    <div class="border-top pt-3 mt-3">
                        <h6 class="mb-3"><i class="bi bi-list-check me-2"></i>Binance 详细指标</h6>
                        
                        <!-- 验证信息 -->
                        <div class="row mb-3">
                            <div class="col-12">
                                <div class="row text-center gx-1"> <!-- 减小列间距 -->
                                    <div class="col">
                                        <small class="text-muted d-block">验证次数</small>
                                        <strong>${validations}</strong>
                                    </div>
                                    <div class="col">
                                        <small class="text-muted d-block">验证通过</small>
                                        <strong class="text-success">${validationsSuccess}</strong>
                                    </div>
                                    <div class="col">
                                        <small class="text-muted d-block">验证失败</small>
                                        <strong class="text-danger">${metrics.validations_failed || 0}</strong>
                                    </div>
                                    <div class="col">
                                        <small class="text-muted d-block">验证统计</small>
                                        <span class="badge ${validationSuccessRate >= 99 ? 'bg-success' : validationSuccessRate >= 95 ? 'bg-warning' : 'bg-danger'}">
                                            ${validationSuccessRate.toFixed(1)}%
                                        </span>
                                    </div>
                                    <div class="col">
                                        <small class="text-muted d-block">警告数</small>
                                        <strong class="${warnings > 0 ? 'text-warning' : ''}">
                                            <i class="bi bi-exclamation-triangle me-1"></i>${warnings}
                                        </strong>
                                    </div>  
                                    <div class="col">
                                        <small class="text-muted d-block">缓冲队列</small>
                                        <strong>${avgPendingBuffer.toFixed(2)}</strong>
                                    </div>      
                                </div>
                            </div>
                        </div>
                        
                        <!-- 其他指标 -->
                        <div class="row mb-3">
                            <div class="col-12">
                                <div class="row text-center gx-1">
                                    <div class="col">
                                        <small class="text-muted d-block">T0 Signal</small>
                                        <strong>${t0Count}</strong>
                                    </div>
                                    <div class="col">
                                        <small class="text-muted d-block">T0率</small>
                                        <strong>${t0Rate.toFixed(2)}%</strong>
                                    </div>
                                    <div class="col">
                                        <small class="text-muted d-block">平均T0/min</small>
                                        <strong>${t0AvgPerMinute.toFixed(2)}</strong>
                                    </div>
                                    <div class="col">
                                        <small class="text-muted d-block">平均T0间隔</small>
                                        <strong>${avgSignalInterval.toFixed(0)}ms</strong>
                                    </div>
                                    <div class="col">
                                        <small class="text-muted d-block">平均冷却</small>
                                        <strong>${avgCooldownInterval.toFixed(0)}ms</strong>
                                    </div>
                                    <div class="col">
                                        <small class="text-muted d-block">Up率</small>
                                        <strong>${upPercent.toFixed(1)}%</strong>
                                    </div>
                                    <div class="col">
                                        <small class="text-muted d-block">Down率</small>
                                        <strong>${downPercent.toFixed(1)}%</strong>
                                    </div>
                                </div>    
                            </div>    
                        </div>
                        <div class="row mb-3">
                            <div class="col-12">
                                <div class="row text-center gx-1">
                                    <div class="col">
                                        <small class="text-muted d-block">最近1分钟T0</small>
                                        <strong>${t0RecentPerMinute.toFixed(0)}</strong>
                                    </div>
                                    <div class="col">
                                        <small class="text-muted d-block">最近信号间隔</small>
                                        <strong>${recentSignalInterval.toFixed(0)}</strong>
                                    </div>
                                    <div class="col">
                                        <small class="text-muted d-block">最近Up率</small>
                                        <strong>${recentUpPercent.toFixed(1)}%</strong>
                                    </div>
                                    <div class="col">
                                        <small class="text-muted d-block">最近Down率</small>
                                        <strong>${recentDownPercent.toFixed(1)}%</strong>
                                    </div>
                                </div>    
                            </div>    
                        </div>
                    </div>
                `;
            }
            
            // Polymarket 指标
            else if (adapter === 'polymarket' || metrics.adapter_type === 'polymarket') {
                const bookCount = metrics.book_count || 0;
                const priceChangeCount = metrics.price_change_count || 0;
                
                // 消息数详情
                const messagesDetails = `
                    <div class="mt-1">
                        <small class="text-muted d-block mb-1">消息详情：</small>
                        <div class="d-flex justify-content-center">
                            <span class="badge bg-info me-1">订单簿: ${bookCount}</span>
                            <span class="badge bg-primary">价格: ${priceChangeCount}</span>
                        </div>
                    </div>
                `;
                
                // 通用指标
                commonMetrics = `
                    <div class="row mb-3">
                        <div class="col-6 text-center">
                            <h5 class="mb-1">${successRate.toFixed(1)}%</h5>
                            <small class="text-muted">成功率</small>
                        </div>
                        <div class="col-6 text-center">
                            <h5 class="mb-1">${messages}</h5>
                            <small class="text-muted">总消息数</small>
                            ${messagesDetails}
                        </div>
                    </div>
                `;
                
                // Polymarket 详细指标（只显示延迟分布）
                const p50 = metrics.p50_latency_ms || 0;
                const p95 = metrics.p95_latency_ms || 0;
                const p99 = metrics.p99_latency_ms || 0;
                
                specificMetrics = `
                    <div class="border-top pt-3 mt-3">
                        <h6 class="mb-3"><i class="bi bi-bar-chart me-2"></i>Polymarket 延迟分布</h6>
                        
                        <!-- 延迟分布 -->
                        <div class="row mb-3">
                            <div class="col-12">
                                <div class="row text-center">
                                    <div class="col-4">
                                        <small class="text-muted d-block">P50 延迟</small>
                                        <strong>${p50.toFixed(0)}ms</strong>
                                    </div>
                                    <div class="col-4">
                                        <small class="text-muted d-block">P95 延迟</small>
                                        <strong>${p95.toFixed(0)}ms</strong>
                                    </div>
                                    <div class="col-4">
                                        <small class="text-muted d-block">P99 延迟</small>
                                        <strong>${p99.toFixed(0)}ms</strong>
                                    </div>
                                </div>
                            </div>
                        </div>
                        
                        <!-- 延迟对比 -->
                        <div class="row mb-3">
                            <div class="col-12">
                                <div class="row text-center gx-1">
                                    <div class="col-6">
                                        <small class="text-muted d-block">最大延迟</small>
                                        <strong class="text-danger">${(metrics.max_latency_ms || 0).toFixed(0)}ms</strong>
                                    </div>
                                    <div class="col-6">
                                        <small class="text-muted d-block">最小延迟</small>
                                        <strong class="text-success">${(metrics.min_latency_ms || 0).toFixed(0)}ms</strong>
                                    </div>
                                </div>        
                            </div>    
                        </div>
                    </div>
                `;
            }
            
            // 未知适配器类型
            else {
                commonMetrics = `
                    <div class="row mb-2">
                        <div class="col-6 text-center">
                            <h5 class="mb-1">${successRate.toFixed(1)}%</h5>
                            <small class="text-muted">成功率</small>
                        </div>
                        <div class="col-6 text-center">
                            <h5 class="mb-1">${messages}</h5>
                            <small class="text-muted">消息数</small>
                        </div>
                    </div>
                `;
                
                specificMetrics = `
                    <div class="border-top pt-2 mt-2">
                        <small class="text-muted">可用指标: ${Object.keys(metrics).length} 个</small>
                        <div class="mt-1">
                            <small class="badge bg-secondary me-1">${metrics.adapter_type || 'unknown'}</small>
                        </div>
                    </div>
                `;
            }
            
            // 订阅列表部分 - 使用本地存储保存折叠状态
            let subscribedSection = '';
            if (subscribedCount > 0) {
                // 检查折叠状态（先从实例状态获取，然后从本地存储获取）
                let isCollapsed = this.collapseStates[adapter] === false;
                
                // 尝试从本地存储获取状态
                try {
                    const storedState = localStorage.getItem(`collapse_${adapter}`);
                    if (storedState !== null) {
                        isCollapsed = storedState === 'collapsed';
                    }
                } catch (e) {
                    console.warn('无法访问本地存储:', e);
                }
                
                // 简单的唯一ID
                const uniqueId = `subscribed-${adapter}-${index}`;
                
                // 决定初始状态和图标
                const collapseClass = isCollapsed ? '' : 'show';
                const buttonIcon = isCollapsed ? 'bi-chevron-down' : 'bi-chevron-up';
                
                subscribedSection = `
                    <div class="border-top pt-3 mt-3">
                        <div class="d-flex justify-content-between align-items-center mb-2">
                            <h6 class="mb-0">
                                <i class="bi bi-list-ul me-2"></i>
                                订阅列表 <span class="badge bg-secondary">${subscribedCount}</span>
                            </h6>
                            <button class="btn btn-sm btn-outline-secondary subscription-toggle" 
                                    type="button" 
                                    data-adapter="${adapter}"
                                    data-target="#${uniqueId}">
                                <i class="bi ${buttonIcon}"></i>
                            </button>
                        </div>
                        <div class="collapse ${collapseClass}" id="${uniqueId}">
                            <div class="subscribed-symbols">
                                ${subscribedSymbols.map((symbol, idx) => {
                                    // 简短的显示，完整内容在title中
                                    const shortSymbol = symbol.length > 12 ? symbol.substring(0, 12) + '...' : symbol;
                                    return `
                                    <div class="d-flex align-items-center mb-1">
                                        <span class="badge bg-light text-dark border me-2" 
                                            title="${symbol}"
                                            style="max-width: 180px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">
                                            ${shortSymbol}
                                        </span>
                                        <small class="text-muted">${idx + 1}</small>
                                    </div>
                                    `;
                                }).join('')}
                            </div>
                        </div>
                    </div>
                `;
            } else {
                subscribedSection = `
                    <div class="border-top pt-3 mt-3">
                        <div class="text-center text-muted py-2">
                            <i class="bi bi-info-circle me-2"></i>
                            无订阅列表
                        </div>
                    </div>
                `;
            }
            
            const card = `
                <div class="col-lg-6 col-md-12 mb-4">
                    <div class="card h-100">
                        <div class="card-header d-flex justify-content-between align-items-center">
                            <div>
                                <h5 class="mb-0">${adapter.toUpperCase()}</h5>
                                <small class="text-muted">${metrics.adapter_type || adapter}</small>
                            </div>
                            <div class="d-flex align-items-center">
                                <span class="badge bg-${isConnected ? 'success' : 'danger'} me-2 px-3 py-1">
                                    ${isConnected ? '已连接' : '未连接'}
                                </span>
                                ${connectionIcon}
                            </div>
                        </div>
                        
                        <div class="card-body">
                            <!-- 延迟显示 -->
                            <div class="text-center mb-4">
                                <div class="d-flex justify-content-center align-items-end">
                                    <h1 class="text-${latencyColor} display-5 me-2">${latency.toFixed(1)}</h1>
                                    <small class="text-muted">ms</small>
                                </div>
                                <small class="text-muted">平均延迟</small>
                            </div>
                            
                            <!-- 通用指标 -->
                            ${commonMetrics}
                            
                            <!-- 适配器特定指标 -->
                            ${specificMetrics}
                            
                            <!-- 订阅列表 -->
                            ${subscribedSection}
                        </div>
                        
                        <div class="card-footer bg-transparent border-top-0">
                            <div class="d-flex justify-content-between align-items-center">
                                <small class="text-muted">
                                    <i class="bi bi-clock me-1"></i>
                                    更新: ${new Date().toLocaleTimeString()}
                                </small>
                                <small class="text-muted">
                                    最大延迟: <span class="${metrics.max_latency_ms > 1000 ? 'text-danger' : 'text-muted'}">${(metrics.max_latency_ms || 0).toFixed(0)}ms</span>
                                </small>
                            </div>
                        </div>
                    </div>
                </div>
            `;
            
            container.innerHTML += card;
        });
        
        // 如果没有适配器，显示提示
        if (Object.keys(summary).length === 0) {
            container.innerHTML = `
                <div class="col-12 text-center py-5">
                    <i class="bi bi-inbox display-1 text-muted"></i>
                    <p class="mt-3">等待数据...</p>
                    <small class="text-muted">适配器正在启动中...</small>
                </div>
            `;
        }
        
        // 重新绑定折叠按钮事件
        this._bindSubscriptionToggleEvents();
    }

    // 绑定订阅列表折叠按钮事件
    _bindSubscriptionToggleEvents() {
        // 移除旧的事件监听器
        const oldButtons = document.querySelectorAll('.subscription-toggle');
        oldButtons.forEach(button => {
            button.removeEventListener('click', this._handleToggleClick);
        });
        
        // 绑定新的事件
        const buttons = document.querySelectorAll('.subscription-toggle');
        buttons.forEach(button => {
            button.addEventListener('click', this._handleToggleClick);
        });
    }

    // 手动初始化折叠功能的辅助方法
    _initializeCollapse() {
        // 为所有折叠按钮添加点击事件
        const toggleButtons = document.querySelectorAll('.toggle-subscriptions');
        
        toggleButtons.forEach(button => {
            // 移除之前的事件监听器，避免重复绑定
            button.removeEventListener('click', this._handleToggleClick);
            
            // 添加新的点击事件
            button.addEventListener('click', this._handleToggleClick.bind(this));
        });
    }

    // 处理折叠按钮点击事件
    _handleToggleClick(event) {
        const button = event.currentTarget;
        const adapter = button.getAttribute('data-adapter');
        const targetId = button.getAttribute('data-target');
        const targetElement = document.querySelector(targetId);
        const icon = button.querySelector('i');
        
        if (targetElement) {
            // 切换显示/隐藏
            if (targetElement.classList.contains('show')) {
                // 折叠
                targetElement.classList.remove('show');
                icon.classList.remove('bi-chevron-up');
                icon.classList.add('bi-chevron-down');
                // 保存状态到本地存储
                this._saveCollapseState(adapter, 'collapsed');
            } else {
                // 展开
                targetElement.classList.add('show');
                icon.classList.remove('bi-chevron-down');
                icon.classList.add('bi-chevron-up');
                // 保存状态到本地存储
                this._saveCollapseState(adapter, 'expanded');
            }
        }
    }

    // 保存折叠状态到本地存储
    _saveCollapseState(adapter, state) {
        try {
            localStorage.setItem(`collapse_${adapter}`, state);
            // 同时更新实例状态
            this.collapseStates[adapter] = state === 'expanded';
        } catch (e) {
            console.warn('无法保存到本地存储:', e);
        }
    }

    // 获取折叠状态
    _getCollapseState(adapter) {
        try {
            const storedState = localStorage.getItem(`collapse_${adapter}`);
            if (storedState !== null) {
                return storedState === 'expanded';
            }
        } catch (e) {
            console.warn('无法从本地存储读取:', e);
        }
        
        // 默认展开
        return true;
    }
    
    updateMetricsTable(summary) {
        const tbody = document.getElementById('metrics-body');
        if (!tbody) {
            console.error('❌ 找不到 #metrics-body 表格体');
            return;
        }
        
        tbody.innerHTML = '';
        
        Object.entries(summary).forEach(([adapter, metrics]) => {
            const latency = metrics.avg_latency_ms || 0;
            const successRate = (metrics.success_rate || 0) * 100;
            const messages = metrics.messages_received || 0;
            const isConnected = metrics.is_connected || false;
            const lastUpdate = metrics.last_update || new Date().toLocaleTimeString();
            
            const row = `
                <tr>
                    <td><strong>${adapter}</strong></td>
                    <td>
                        <span class="badge bg-${latency < 50 ? 'success' : latency < 100 ? 'warning' : 'danger'}">
                            ${latency.toFixed(1)}ms
                        </span>
                    </td>
                    <td>
                        <div class="progress" style="height: 20px;">
                            <div class="progress-bar ${successRate > 95 ? 'bg-success' : successRate > 80 ? 'bg-warning' : 'bg-danger'}" 
                                 role="progressbar" 
                                 style="width: ${successRate}%">
                                ${successRate.toFixed(1)}%
                            </div>
                        </div>
                    </td>
                    <td>${messages}</td>
                    <td>
                        <span class="badge ${isConnected ? 'bg-success' : 'bg-danger'}">
                            ${isConnected ? '✓ 已连接' : '✗ 未连接'}
                        </span>
                    </td>
                    <td>${lastUpdate}</td>
                </tr>
            `;
            
            tbody.innerHTML += row;
        });
        
        if (Object.keys(summary).length === 0) {
            tbody.innerHTML = `
                <tr>
                    <td colspan="6" class="text-center text-muted py-4">
                        <i class="bi bi-database-slash"></i> 暂无数据
                    </td>
                </tr>
            `;
        }
    }
    
    updateCharts(summary) {
        // 如果没有开始时间，使用当前时间作为参考
        if (!this.chartStartTime) {
            this.chartStartTime = Date.now() / 1000;
        }
        
        const now = Date.now() / 1000;
        const elapsed = now - this.chartStartTime;
        
        Object.entries(summary).forEach(([adapter, metrics]) => {
            const latency = metrics.avg_latency_ms || 0;
            const successRate = (metrics.success_rate || 0) * 100;
            
            // 初始化历史数据
            if (!this.dataHistory[adapter]) {
                this.dataHistory[adapter] = {
                    latency: [],
                    success: []
                };
            }
            
            // 添加新数据点
            this.dataHistory[adapter].latency.push({ x: elapsed, y: latency });
            this.dataHistory[adapter].success.push({ x: elapsed, y: successRate });
            
            // 保持最近100个数据点
            if (this.dataHistory[adapter].latency.length > 100) {
                this.dataHistory[adapter].latency.shift();
                this.dataHistory[adapter].success.shift();
            }
        });
        
        // 更新延迟图表
        if (this.charts.latency) {
            const latencyDatasets = Object.entries(this.dataHistory).map(([adapter, data]) => ({
                label: adapter,
                data: data.latency,
                borderColor: this.getColor(adapter),
                backgroundColor: 'transparent',
                tension: 0.1,
                fill: false,
                pointRadius: 2,
                pointHoverRadius: 4
            }));
            
            this.charts.latency.data.datasets = latencyDatasets;
            this.charts.latency.update('none');
        }
        
        // 更新成功率图表
        if (this.charts.success) {
            const successDatasets = Object.entries(this.dataHistory).map(([adapter, data]) => ({
                label: adapter,
                data: data.success,
                borderColor: this.getColor(adapter),
                backgroundColor: 'transparent',
                tension: 0.1,
                fill: false,
                pointRadius: 2,
                pointHoverRadius: 4
            }));
            
            this.charts.success.data.datasets = successDatasets;
            this.charts.success.update('none');
        }
    }

    resetCharts() {
        console.log('重置图表数据...');
        this.dataHistory = {};
        this.chartStartTime = null;
        
        if (this.charts.latency) {
            this.charts.latency.data.datasets = [];
            this.charts.latency.update();
        }
        
        if (this.charts.success) {
            this.charts.success.data.datasets = [];
            this.charts.success.update();
        }
    }
    
    updateStats(testInfo) {
        const container = document.getElementById('test-stats');
        if (!container) {
            console.error('❌ 找不到 #test-stats 容器');
            return;
        }
        
        // 获取开始时间
        let startTimeDisplay = 'N/A';
        if (this.startTime) {
            startTimeDisplay = new Date(this.startTime).toLocaleTimeString();
        } else if (testInfo && testInfo.start_time) {
            startTimeDisplay = new Date(testInfo.start_time).toLocaleTimeString();
        }
        
        // 计算已运行时间
        let elapsedTimeDisplay = '00:00:00';
        if (testInfo && testInfo.elapsed_hours) {
            const elapsedSeconds = testInfo.elapsed_hours * 3600;
            elapsedTimeDisplay = this.formatDuration(elapsedSeconds);
        } else if (this.startTime) {
            const elapsedSeconds = (Date.now() - this.startTime) / 1000;
            elapsedTimeDisplay = this.formatDuration(elapsedSeconds);
        }
        
        // 移除状态显示，因为顶部和左侧已经有了
        let additionalInfo = '';
        if (testInfo && testInfo.duration_hours) {
            // 将小时转换为秒
            const durationSeconds = testInfo.duration_hours * 3600;
            const durationFormatted = this.formatDuration(durationSeconds);
            additionalInfo = `
                <div class="mb-2">
                    <small class="text-muted">预设时长:</small>
                    <div><strong>${durationFormatted}</strong></div>
                </div>
            `;
        }
        
        container.innerHTML = `
            <h6>运行信息</h6>
            ${additionalInfo}
            <div class="mb-2">
                <small class="text-muted">启动时间:</small>
                <div><strong id="start-time">${startTimeDisplay}</strong></div>
            </div>
            <div class="mb-2">
                <small class="text-muted">已运行:</small>
                <div><strong id="elapsed-time">${elapsedTimeDisplay}</strong></div>
            </div>
            <div class="mb-2">
                <small class="text-muted">总数据点:</small>
                <div><strong id="total-data-points">${this.totalDataPoints || 0}</strong></div>
            </div>
        `;
        
        // 同时更新顶部栏的状态信息
        this._updateHeaderStats(testInfo);
    }

    // 新增方法：更新顶部状态栏
    _updateHeaderStats(testInfo) {
        const statusElement = document.getElementById('status-indicator');
        const durationElement = document.getElementById('current-duration');
        
        if (!statusElement || !durationElement) {
            return;
        }
        
        // 更新状态
        const isMonitoring = testInfo && testInfo.is_monitoring;
        const statusText = isMonitoring ? '运行中' : '已停止';
        const statusClass = isMonitoring ? 'bg-success' : 'bg-secondary';
        const statusIcon = isMonitoring ? 'bi-play-circle' : 'bi-stop-circle';
        
        statusElement.innerHTML = `
            <span class="badge ${statusClass}">
                <i class="bi ${statusIcon} me-1"></i>${statusText}
            </span>
        `;
        
        // 更新时长
        if (testInfo && testInfo.elapsed_hours) {
            const elapsedSeconds = testInfo.elapsed_hours * 3600;
            durationElement.textContent = `已运行: ${this.formatDuration(elapsedSeconds)}`;
        } else {
            durationElement.textContent = '未运行';
        }
    }

    updateAdaptersToOffline() {
        console.log('标记所有适配器为离线状态');
        
        // 如果有缓存的上一次数据，使用它作为基础
        const offlineSummary = {};
        
        // 获取已知适配器列表（可以从已有数据或配置中获取）
        let adapters = [];
        
        if (this.lastSummary && Object.keys(this.lastSummary).length > 0) {
            // 使用上次收到的数据
            adapters = Object.keys(this.lastSummary);
            console.log('使用缓存的适配器列表:', adapters);
        } else {
            // 默认适配器列表（根据实际情况调整）
            adapters = ['binance', 'polymarket'];
            console.log('使用默认适配器列表:', adapters);
        }
        
        // 为每个适配器创建离线状态
        adapters.forEach(adapter => {
            offlineSummary[adapter] = {
                avg_latency_ms: 0,
                success_rate: 0,
                messages_received: 0,
                is_connected: false,
                last_update: new Date().toLocaleTimeString()
            };
        });
        
        // 更新仪表板显示离线状态
        this.updateDashboard({ summary: offlineSummary });
    }
    
    updateStatus() {
        const connectionStatus = document.getElementById('connection-status');
        const connectionStatusDetail = document.getElementById('connection-status-detail');
        const testStatus = document.getElementById('test-status');
        const testStatusDetail = document.getElementById('test-status-detail');
        const connectionInfo = document.getElementById('connection-info');
        const testInfo = document.getElementById('test-info');
        
        // 更新顶部导航栏的连接状态
        if (connectionStatus) {
            if (this.connected) {
                connectionStatus.className = 'badge bg-success me-3';
                connectionStatus.textContent = '已连接';
            } else {
                connectionStatus.className = 'badge bg-danger me-3';
                connectionStatus.textContent = '未连接';
            }
        }
        
        // 更新左侧面板的详细连接状态
        if (connectionStatusDetail) {
            if (this.connected) {
                connectionStatusDetail.className = 'badge bg-success';
                connectionStatusDetail.textContent = '已连接';
                if (connectionInfo) {
                    connectionInfo.textContent = this.testRunning ? '实时数据推送中' : '连接正常';
                }
            } else {
                connectionStatusDetail.className = 'badge bg-danger';
                connectionStatusDetail.textContent = '连接中...';
                if (connectionInfo) {
                    connectionInfo.textContent = '正在尝试连接服务器';
                }
            }
        }
        
        // 更新顶部导航栏的测试状态
        if (testStatus) {
            if (this.testRunning) {
                testStatus.className = 'badge bg-success';
                testStatus.textContent = '运行中';
            } else {
                testStatus.className = 'badge bg-secondary';
                testStatus.textContent = '已停止';
            }
        }
        
        // 更新左侧面板的详细测试状态
        if (testStatusDetail) {
            if (this.testRunning) {
                testStatusDetail.className = 'badge bg-success';
                testStatusDetail.textContent = '运行中';
                if (testInfo) {
                    testInfo.textContent = '监控系统正在自动运行';
                }
            } else {
                testStatusDetail.className = 'badge bg-secondary';
                testStatusDetail.textContent = '已停止';
                if (testInfo) {
                    testInfo.textContent = '监控系统已停止';
                }
            }
        }
    }
    
    startElapsedTimer() {
        // 更新启动时间显示
        const startTimeEl = document.getElementById('start-time');
        if (startTimeEl) {
            startTimeEl.textContent = new Date(this.startTime).toLocaleTimeString();
        }
        
        // 每秒更新已运行时间
        setInterval(() => {
            const elapsedSeconds = Math.floor((Date.now() - this.startTime) / 1000);
            const hours = Math.floor(elapsedSeconds / 3600);
            const minutes = Math.floor((elapsedSeconds % 3600) / 60);
            const seconds = elapsedSeconds % 60;
            
            const elapsedTimeEl = document.getElementById('elapsed-time');
            if (elapsedTimeEl) {
                elapsedTimeEl.textContent = `${hours.toString().padStart(2, '0')}:${minutes.toString().padStart(2, '0')}:${seconds.toString().padStart(2, '0')}`;
            }
        }, 1000);
    }
    
    updateStartTime(timestamp) {
        this.startTime = new Date(timestamp).getTime() || Date.now();
        const startTimeEl = document.getElementById('start-time');
        if (startTimeEl) {
            startTimeEl.textContent = new Date(this.startTime).toLocaleTimeString();
        }
    }
    
    // 通过HTTP API拉取数据（备用方法）
    async fetchDataViaHTTP() {
        try {
            console.log('通过HTTP API拉取数据...');
            
            // 同时获取状态和指标数据
            const [statusRes, metricsRes] = await Promise.allSettled([
                fetch('/api/status'),
                fetch('/api/metrics')
            ]);
            
            // 处理状态响应
            if (statusRes.status === 'fulfilled' && statusRes.value.ok) {
                const status = await statusRes.value.json();
                console.log('服务状态:', status);
                
                this.connected = status.connected_clients > 0;
                this.testRunning = status.test_running;
                this.updateStatus();
            }
            
            // 处理指标响应
            if (metricsRes.status === 'fulfilled' && metricsRes.value.ok) {
                const metrics = await metricsRes.value.json();
                console.log('获取到指标数据:', metrics);
                
                if (metrics.summary && Object.keys(metrics.summary).length > 0) {
                    this.updateDashboard({ summary: metrics.summary });
                }
            }
            
            // 如果两个请求都失败，尝试重新连接WebSocket
            if (statusRes.status === 'rejected' && metricsRes.status === 'rejected') {
                console.error('HTTP请求全部失败，尝试重新连接WebSocket');
                if (!this.connected) {
                    this.connectWebSocket();
                }
            }
            
        } catch (error) {
            console.error('HTTP数据拉取失败:', error);
        }
    }
    
    showNotification(title, message, type = 'info') {
        console.log(`[${type.toUpperCase()}] ${title}: ${message}`);
        
        // 创建通知元素
        const notification = document.createElement('div');
        const alertClass = {
            'success': 'alert-success',
            'error': 'alert-danger',
            'warning': 'alert-warning',
            'info': 'alert-info'
        }[type] || 'alert-info';
        
        notification.className = `alert ${alertClass} alert-dismissible fade show`;
        notification.style.position = 'fixed';
        notification.style.top = '20px';
        notification.style.right = '20px';
        notification.style.zIndex = '9999';
        notification.style.minWidth = '300px';
        notification.style.maxWidth = '500px';
        
        const icon = {
            'success': 'check-circle',
            'error': 'exclamation-circle',
            'warning': 'exclamation-triangle',
            'info': 'info-circle'
        }[type] || 'info-circle';
        
        notification.innerHTML = `
            <div class="d-flex align-items-center">
                <i class="bi bi-${icon} me-2"></i>
                <div>
                    <strong>${title}</strong>
                    <div class="small">${message}</div>
                </div>
            </div>
            <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
        `;
        
        // 添加到页面
        document.body.appendChild(notification);
        
        // 5秒后自动移除
        setTimeout(() => {
            if (notification.parentNode) {
                notification.remove();
            }
        }, 5000);
    }
    
    getColor(adapter) {
        const colors = {
            'binance': '#f0b90b',
            'polymarket': '#8b5cf6',
            'default': '#3b82f6'
        };
        
        return colors[adapter] || colors.default;
    }

    formatDuration(seconds) {
        if (seconds === undefined || seconds === null) {
            return '00:00:00';
        }
        
        const hours = Math.floor(seconds / 3600);
        const minutes = Math.floor((seconds % 3600) / 60);
        const secs = Math.floor(seconds % 60);
        
        if (hours > 0) {
            return `${hours}:${minutes.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
        } else if (minutes > 0) {
            return `${minutes}:${secs.toString().padStart(2, '0')}`;
        } else {
            return `0:${secs.toString().padStart(2, '0')}`;
        }
    }

    formatTime(seconds) {
        if (seconds >= 3600) {
            return `${(seconds / 3600).toFixed(1)}小时`;
        } else if (seconds >= 60) {
            return `${(seconds / 60).toFixed(1)}分钟`;
        } else {
            return `${seconds}秒`;
        }
    }
}

// 初始化仪表板
document.addEventListener('DOMContentLoaded', () => {
    console.log('DOMContentLoaded事件触发');
    console.log('页面加载完成，开始初始化...');
    
    try {
        window.dashboard = new MarketDashboard();
        console.log('✅ MarketDashboard初始化成功');
        
    } catch (error) {
        console.error('❌ MarketDashboard初始化失败:', error);
        alert(`初始化失败: ${error.message}\n请查看控制台获取详细信息`);
    }
});

// 添加全局错误处理
window.addEventListener('error', (event) => {
    console.error('全局错误:', event.error || event.message);
});

// 添加未处理的Promise拒绝处理
window.addEventListener('unhandledrejection', (event) => {
    console.error('未处理的Promise拒绝:', event.reason);
});