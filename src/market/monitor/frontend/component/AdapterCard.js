export default {
    template: `
        <div class="card h-100">
            <!-- 卡片头部 -->
            <div class="card-header d-flex justify-content-between align-items-center"
                 :style="headerStyle">
                <div>
                    <h5 class="mb-0">{{ displayName }}</h5>
                    <small class="text-muted">{{ adapterData.adapter_type || adapterName }}</small>
                </div>
                <div class="d-flex align-items-center">
                    <span class="badge me-2 px-3 py-1"
                          :class="connectionClass">
                        {{ connectionText }}
                    </span>
                    <i class="bi" :class="connectionIcon"></i>
                </div>
            </div>
            
            <div class="card-body">
                <!-- 主要指标 -->
                <div class="text-center mb-4">
                    <div class="d-flex justify-content-center align-items-end">
                        <h1 class="display-5 me-2" :class="latencyClass">
                            {{ formattedLatency }}
                        </h1>
                        <small class="text-muted">ms</small>
                    </div>
                    <small class="text-muted">平均延迟</small>
                </div>
                
                <!-- 次要指标 -->
                <div class="row mb-3">
                    <div class="col-6 text-center">
                        <h5 class="mb-1">{{ formattedSuccessRate }}%</h5>
                        <small class="text-muted">成功率</small>
                    </div>
                    <div class="col-6 text-center">
                        <h5 class="mb-1">{{ adapterData.messages_received || 0 }}</h5>
                        <small class="text-muted">总消息数</small>
                        
                        <!-- 消息详情 -->
                        <div v-if="hasMessageDetails" class="mt-1">
                            <small class="text-muted d-block mb-1">消息详情：</small>
                            <div class="d-flex justify-content-center">
                                <template v-for="(count, type) in messageDetails" :key="type">
                                    <span class="badge bg-info me-1">{{ type }}: {{ count }}</span>
                                </template>
                            </div>
                        </div>
                    </div>
                </div>
                
                <!-- 详细指标部分 -->
                <div v-for="section in config.sections" :key="section.name" class="border-top pt-3 mt-3">
                    <div class="d-flex justify-content-between align-items-center mb-2">
                        <h6 class="mb-0">
                            <i :class="'bi ' + section.icon + ' me-2'"></i>
                            {{ section.title }}
                        </h6>
                        <button class="btn btn-sm btn-outline-secondary" 
                                @click="toggleSection(section.name)">
                            <i class="bi" :class="sectionCollapsed(section.name) ? 'bi-chevron-down' : 'bi-chevron-up'"></i>
                        </button>
                    </div>
                    
                    <div v-if="!sectionCollapsed(section.name)" class="mt-2">
                        <div class="row gx-1">
                            <div v-for="metricKey in getSectionMetrics(section.name)" 
                                 :key="metricKey"
                                 class="col mb-2 text-center">
                                <small class="text-muted d-block">{{ getMetricLabel(metricKey) }}</small>
                                <!-- 判断是否应该显示图标 -->
                                <template v-if="shouldDisplayWithIcon(metricKey)">
                                    <div>
                                        <i :class="getMetricIcon(metricKey) + ' ' + getMetricClass(metricKey)"></i>
                                        <strong :class="getMetricClass(metricKey)">
                                            {{ formatMetric(adapterData[metricKey], metricKey) }}
                                        </strong>
                                    </div>
                                </template>
                                <template v-else>
                                    <strong :class="getMetricClass(metricKey)">
                                        {{ formatMetric(adapterData[metricKey], metricKey) }}
                                    </strong>
                                </template>
                            </div>
                        </div>
                    </div>
                </div>
                
                <!-- 订阅列表 -->
                <div v-if="hasSubscriptions" class="border-top pt-3 mt-3">
                    <div class="d-flex justify-content-between align-items-center mb-2">
                        <h6 class="mb-0">
                            <i class="bi bi-list-ul me-2"></i>
                            订阅列表 <span class="badge bg-secondary">{{ subscriptionCount }}</span>
                        </h6>
                        <button class="btn btn-sm btn-outline-secondary" 
                                @click="toggleSubscriptions">
                            <i class="bi" :class="subscriptionsCollapsed ? 'bi-chevron-down' : 'bi-chevron-up'"></i>
                        </button>
                    </div>
                    
                    <div v-if="!subscriptionsCollapsed" class="subscriptions mt-2">
                        <div class="d-flex flex-wrap gap-1">
                            <span v-for="symbol in adapterData.subscribed_symbols.slice(0, 12)" 
                                  :key="symbol"
                                  class="badge bg-light text-dark border"
                                  :title="symbol">
                                {{ truncateSymbol(symbol) }}
                            </span>
                            <span v-if="adapterData.subscribed_symbols.length > 12" 
                                  class="badge bg-secondary">
                                +{{ adapterData.subscribed_symbols.length - 12 }} 更多
                            </span>
                        </div>
                    </div>
                </div>
            </div>
            
            <!-- 卡片页脚 -->
            <div class="card-footer bg-transparent border-top-0">
                <div class="d-flex justify-content-between align-items-center">
                    <small class="text-muted">
                        <i class="bi bi-clock me-1"></i>
                        更新: {{ adapterData.lastUpdate || '--:--:--' }}
                    </small>
                    <small class="text-muted">
                        最大延迟: 
                        <span :class="maxLatencyClass">
                            {{ formattedMaxLatency }}ms
                        </span>
                    </small>
                </div>
            </div>
        </div>
    `,
    
    props: {
        adapterName: String,
        adapterData: Object,
        config: Object
    },
    
    data() {
        return {
            collapsedSections: {},
            subscriptionsCollapsed: true
        };
    },
    
    computed: {
        displayName() {
            return this.config?.name || this.adapterName.toUpperCase();
        },
        
        headerStyle() {
            return {
                backgroundColor: (this.config?.color || '#3b82f6') + '20',
                borderColor: this.config?.color || '#3b82f6'
            };
        },
        
        connectionClass() {
            return this.adapterData.is_connected ? 'bg-success' : 'bg-danger';
        },
        
        connectionText() {
            return this.adapterData.is_connected ? '已连接' : '未连接';
        },
        
        connectionIcon() {
            return this.adapterData.is_connected ? 
                'bi-check-circle-fill text-success' : 
                'bi-x-circle-fill text-danger';
        },
        
        latencyClass() {
            const latency = this.adapterData.avg_latency_ms || 0;
            const thresholds = this.config?.metrics?.avg_latency_ms?.thresholds;
            
            if (thresholds) {
                if (latency <= thresholds.good) return 'text-success';
                if (latency <= thresholds.warning) return 'text-warning';
                return 'text-danger';
            }
            
            // 默认阈值
            if (latency < 50) return 'text-success';
            if (latency < 100) return 'text-warning';
            return 'text-danger';
        },
        
        formattedLatency() {
            const latency = this.adapterData.avg_latency_ms || 0;
            const decimals = this.config?.metrics?.avg_latency_ms?.decimals || 1;
            return latency.toFixed(decimals);
        },
        
        formattedSuccessRate() {
            const rate = (this.adapterData.success_rate || 0) * 100;
            const decimals = this.config?.metrics?.success_rate?.decimals || 1;
            return rate.toFixed(decimals);
        },
        
        hasMessageDetails() {
            return this.messageDetails && Object.keys(this.messageDetails).length > 0;
        },
        
        messageDetails() {
            const details = {};
            
            // Binance 消息详情
            if (this.adapterData.trade_count !== undefined) {
                details['交易'] = this.adapterData.trade_count;
            }
            if (this.adapterData.depthUpdate_count !== undefined) {
                details['深度'] = this.adapterData.depthUpdate_count;
            }
            
            // Polymarket 消息详情
            if (this.adapterData.book_count !== undefined) {
                details['订单簿'] = this.adapterData.book_count;
            }
            if (this.adapterData.price_change_count !== undefined) {
                details['价格'] = this.adapterData.price_change_count;
            }
            
            return details;
        },
        
        hasSubscriptions() {
            return this.adapterData.subscribed_symbols?.length > 0;
        },
        
        subscriptionCount() {
            return this.adapterData.subscribed_symbols?.length || 0;
        },
        
        formattedMaxLatency() {
            const max = this.adapterData.max_latency_ms || 0;
            return max.toFixed(0);
        },
        
        maxLatencyClass() {
            const max = this.adapterData.max_latency_ms || 0;
            return max > 1000 ? 'text-danger' : 'text-muted';
        }
    },
    
    methods: {
        toggleSection(sectionName) {
            this.collapsedSections[sectionName] = !this.collapsedSections[sectionName];
        },
        
        sectionCollapsed(sectionName) {
            return !!this.collapsedSections[sectionName];
        },
        
        getSectionMetrics(sectionName) {
            if (!this.config?.metrics) return [];
            
            return Object.keys(this.config.metrics).filter(metricKey => {
                const metric = this.config.metrics[metricKey];
                return metric.group === sectionName;
            });
        },
        
        getMetricLabel(metricKey) {
            return this.config?.metrics?.[metricKey]?.label || metricKey;
        },

        getMetricClass(metricKey) {
            const value = this.adapterData[metricKey] || 0;
            const metricConfig = this.config?.metrics?.[metricKey];
            
            if (!metricConfig?.color) return '';
            
            const colorConfig = metricConfig.color;

            // 条件判断类型
            if (colorConfig.type === 'conditional') {
                for (const condition of colorConfig.conditions) {
                    let meetsCondition = false;
                    
                    switch (condition.condition) {
                        case '>':
                            meetsCondition = value > condition.value;
                            break;
                        case '>=':
                            meetsCondition = value >= condition.value;
                            break;
                        case '<':
                            meetsCondition = value < condition.value;
                            break;
                        case '<=':
                            meetsCondition = value <= condition.value;
                            break;
                        case '=':
                        case '===':
                            meetsCondition = value === condition.value;
                            break;
                        default:
                            meetsCondition = false;
                    }
                    
                    if (meetsCondition) {
                        return condition.class;
                    }
                }
            }
            
            // 静态颜色
            if (colorConfig.type === 'static') {
                return colorConfig.value;
            }
            
            // 基于阈值的动态颜色
            if (colorConfig.type === 'threshold') {
                for (const threshold of colorConfig.thresholds) {
                    if (value >= threshold.min) {
                        return threshold.class;
                    }
                }
            }
            
            // 默认阈值（兼容现有代码）
            if (metricConfig?.thresholds) {
                if (value <= metricConfig.thresholds.good) return 'text-success';
                if (value <= metricConfig.thresholds.warning) return 'text-warning';
                return 'text-danger';
            }
            
            return '';
        },
        
        formatMetric(value, metricKey) {
            const metricConfig = this.config?.metrics?.[metricKey];
            if (!metricConfig) return value || 0;
            
            const val = value || 0;
            
            switch (metricConfig.format) {
                case 'percent':
                    const percent = val * 100;
                    return percent.toFixed(metricConfig.decimals || 1) + '%';
                    
                case 'number':
                    const formatted = val.toFixed(metricConfig.decimals || 0);
                    // 如果有单位配置，添加单位
                    if (metricConfig.unit) {
                        return formatted + metricConfig.unit;
                    }
                    return formatted;
                    
                default:
                    return val;
            }
        },
        
        toggleSubscriptions() {
            this.subscriptionsCollapsed = !this.subscriptionsCollapsed;
        },
        
        truncateSymbol(symbol) {
            if (symbol.length > 12) {
                return symbol.substring(0, 12) + '...';
            }
            return symbol;
        },

        // 判断是否应该显示图标
        shouldDisplayWithIcon(metricKey) {
            return this.config?.metrics?.[metricKey]?.display === 'icon';
        },

        // 获取指标图标
        getMetricIcon(metricKey) {
            const icon = this.config?.metrics?.[metricKey]?.icon;
            return icon ? `bi ${icon}` : '';
        }
    },
    
    mounted() {
        // 默认展开第一个部分
        if (this.config?.sections?.length > 0) {
            this.collapsedSections[this.config.sections[0].name] = false;
        }
    }
};