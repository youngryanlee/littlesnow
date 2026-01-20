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
        
        // 更新适配器状态列表
        this.updateAdapterStatusList(summary);
        
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
        
        Object.entries(summary).forEach(([adapter, metrics]) => {
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
            
            const card = `
                <div class="col-md-3 mb-3">
                    <div class="card h-100">
                        <div class="card-header">
                            <h6 class="mb-0">${adapter.toUpperCase()}</h6>
                        </div>
                        <div class="card-body text-center">
                            <div class="mb-3">
                                <h2 class="text-${latencyColor}">${latency.toFixed(1)}</h2>
                                <small class="text-muted">平均延迟 (ms)</small>
                            </div>
                            <div class="row">
                                <div class="col-6">
                                    <h5>${successRate.toFixed(1)}%</h5>
                                    <small>成功率</small>
                                </div>
                                <div class="col-6">
                                    <h5>${messages}</h5>
                                    <small>消息数</small>
                                </div>
                            </div>
                        </div>
                        <div class="card-footer text-center">
                            ${connectionIcon}
                            <small>${isConnected ? '已连接' : '未连接'}</small>
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
    
    updateAdapterStatusList(summary) {
        const container = document.getElementById('adapter-status-list');
        if (!container) return;
        
        container.innerHTML = '';
        
        Object.entries(summary).forEach(([adapter, metrics]) => {
            const isConnected = metrics.is_connected || false;
            const successRate = (metrics.success_rate || 0) * 100;
            const latency = metrics.avg_latency_ms || 0;
            const messages = metrics.messages_received || 0;
            
            const statusItem = document.createElement('div');
            statusItem.className = 'mb-3';
            
            statusItem.innerHTML = `
                <div class="d-flex justify-content-between align-items-center mb-1">
                    <strong>${adapter.toUpperCase()}</strong>
                    <span class="badge ${isConnected ? 'bg-success' : 'bg-danger'}">
                        ${isConnected ? '在线' : '离线'}
                    </span>
                </div>
                <div class="row small text-muted">
                    <div class="col-6">
                        <div>${successRate.toFixed(1)}%</div>
                        <small>成功率</small>
                    </div>
                    <div class="col-6">
                        <div>${latency.toFixed(0)}ms</div>
                        <small>延迟</small>
                    </div>
                </div>
                <div class="mt-1 small">
                    <i class="bi bi-chat-dots"></i> ${messages} 条消息
                </div>
            `;
            
            container.appendChild(statusItem);
        });
        
        if (Object.keys(summary).length === 0) {
            container.innerHTML = `
                <div class="text-center py-3">
                    <i class="bi bi-database-slash display-6 text-muted"></i>
                    <p class="mt-2">暂无适配器数据</p>
                    <small class="text-muted">等待监控系统启动</small>
                </div>
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
        
        // 移除状态显示，因为顶部和左侧已经有了
        let additionalInfo = '';
        if (testInfo && testInfo.duration_hours) {
            additionalInfo = `
                <div class="mb-2">
                    <small class="text-muted">预设时长:</small>
                    <div><strong>${this.formatDuration(testInfo.duration_hours)}</strong></div>
                </div>
            `;
        }
        
        container.innerHTML = `
            <h6>运行信息</h6>
            ${additionalInfo}
            <div class="mb-2">
                <small class="text-muted">启动时间:</small>
                <div><strong id="start-time">${new Date(this.startTime).toLocaleTimeString()}</strong></div>
            </div>
            <div class="mb-2">
                <small class="text-muted">已运行:</small>
                <div><strong id="elapsed-time">00:00:00</strong></div>
            </div>
            <div class="mb-2">
                <small class="text-muted">总数据点:</small>
                <div><strong id="total-data-points">${this.totalDataPoints}</strong></div>
            </div>
        `;
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