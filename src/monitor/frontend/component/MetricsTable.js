export default {
    template: `
        <div class="table-responsive">
            <table class="table table-hover">
                <thead>
                    <tr>
                        <th>适配器</th>
                        <th>平均延迟</th>
                        <th>成功率</th>
                        <th>消息数</th>
                        <th>连接状态</th>
                        <th>最后更新时间</th>
                    </tr>
                </thead>
                <tbody>
                    <tr v-for="(adapterData, adapterName) in adapters" :key="adapterName">
                        <td><strong>{{ adapterName }}</strong></td>
                        <td>
                            <span class="badge" :class="getLatencyClass(adapterData.avg_latency_ms)">
                                {{ formatLatency(adapterData.avg_latency_ms) }}
                            </span>
                        </td>
                        <td>
                            <div class="progress" style="height: 20px;">
                                <div class="progress-bar" 
                                     :class="getSuccessClass(adapterData.success_rate)"
                                     role="progressbar" 
                                     :style="{ width: (adapterData.success_rate || 0) * 100 + '%' }">
                                    {{ formatSuccessRate(adapterData.success_rate) }}%
                                </div>
                            </div>
                        </td>
                        <td>{{ adapterData.messages_received || 0 }}</td>
                        <td>
                            <span class="badge" :class="adapterData.is_connected ? 'bg-success' : 'bg-danger'">
                                {{ adapterData.is_connected ? '✓ 已连接' : '✗ 未连接' }}
                            </span>
                        </td>
                        <td>{{ adapterData.lastUpdate || '--:--:--' }}</td>
                    </tr>
                    
                    <!-- 无数据提示 -->
                    <tr v-if="Object.keys(adapters).length === 0">
                        <td colspan="6" class="text-center text-muted py-4">
                            <i class="bi bi-database-slash"></i> 暂无数据
                        </td>
                    </tr>
                </tbody>
            </table>
        </div>
    `,
    
    props: {
        adapters: {
            type: Object,
            default: () => ({})
        }
    },
    
    methods: {
        getLatencyClass(latency) {
            const lat = latency || 0;
            if (lat < 50) return 'bg-success';
            if (lat < 100) return 'bg-warning';
            return 'bg-danger';
        },
        
        formatLatency(latency) {
            const lat = latency || 0;
            return lat.toFixed(1) + 'ms';
        },
        
        getSuccessClass(successRate) {
            const rate = (successRate || 0) * 100;
            if (rate > 95) return 'bg-success';
            if (rate > 80) return 'bg-warning';
            return 'bg-danger';
        },
        
        formatSuccessRate(successRate) {
            const rate = (successRate || 0) * 100;
            return rate.toFixed(1);
        }
    }
};