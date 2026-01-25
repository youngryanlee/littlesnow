export default {
    template: `
        <div class="card mb-4">
            <div class="card-header">
                <h5 class="mb-0"><i class="bi bi-info-circle"></i> 系统状态</h5>
            </div>
            <div class="card-body">
                <!-- 连接状态 -->
                <div class="mb-3">
                    <div class="d-flex justify-content-between align-items-center mb-2">
                        <span>WebSocket连接</span>
                        <span class="badge" :class="connectionClass">
                            {{ connectionText }}
                        </span>
                    </div>
                    <small class="text-muted">
                        {{ connectionInfo }}
                    </small>
                </div>
                
                <hr>
                
                <!-- 测试状态 -->
                <div class="mb-3">
                    <div class="d-flex justify-content-between align-items-center mb-2">
                        <span>监控状态</span>
                        <span class="badge" :class="testStatusClass">
                            {{ testStatusText }}
                        </span>
                    </div>
                    <small class="text-muted">
                        {{ testInfo }}
                    </small>
                </div>
                
                <hr>
                
                <!-- 数据统计 -->
                <div>
                    <h6>运行信息</h6>
                    
                    <div class="mb-2">
                        <small class="text-muted">启动时间:</small>
                        <div>
                            <strong>{{ formattedStartTime }}</strong>
                        </div>
                    </div>
                    
                    <div class="mb-2">
                        <small class="text-muted">已运行:</small>
                        <div>
                            <strong>{{ elapsedTime }}</strong>
                        </div>
                    </div>
                    
                    <div class="mb-2">
                        <small class="text-muted">总数据点:</small>
                        <div>
                            <strong>{{ totalDataPoints }}</strong>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    `,
    
    props: {
        connected: Boolean,
        testRunning: Boolean,
        elapsedTime: String,
        startTime: [Number, String],
        totalDataPoints: Number,
        lastUpdate: String
    },
    
    computed: {
        connectionClass() {
            return this.connected ? 'bg-success' : 'bg-danger';
        },
        
        connectionText() {
            return this.connected ? '已连接' : '未连接';
        },
        
        connectionInfo() {
            if (!this.connected) return '正在尝试连接服务器...';
            return this.testRunning ? '实时数据推送中' : '连接正常，监控已停止';
        },
        
        testStatusClass() {
            return this.testRunning ? 'bg-success' : 'bg-secondary';
        },
        
        testStatusText() {
            return this.testRunning ? '运行中' : '已停止';
        },
        
        testInfo() {
            return this.testRunning ? '监控系统正在自动运行' : '监控系统已停止';
        },
        
        formattedStartTime() {
            if (!this.startTime) return '--:--:--';
            return new Date(this.startTime).toLocaleTimeString();
        }
    }
};