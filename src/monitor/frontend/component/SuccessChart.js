export default {
    template: `
        <div class="card mb-4">
            <div class="card-header">
                <h5 class="mb-0">
                    <i class="bi bi-percent"></i> {{ title || '成功率趋势' }}
                    <small v-if="showDebug" class="text-muted ms-2">
                        状态: {{ chartStatus }}
                    </small>
                </h5>
            </div>
            <div class="card-body" style="height:300px; position: relative;">
                <canvas ref="chartCanvas"></canvas>
                <div v-if="showPlaceholder" class="position-absolute top-50 start-50 translate-middle text-center text-muted">
                    <i class="bi bi-percent display-4"></i>
                    <p class="mt-3">等待数据...</p>
                </div>
            </div>
        </div>
    `,

    props: {
        chartData: {
            type: Object,
            required: true,
            default: () => ({})
        },
        title: {
            type: String,
            default: '成功率趋势'
        }
    },

    data() {
        return {
            chart: null,
            mountedReady: false,
            showPlaceholder: true,
            showDebug: true,
            chartStatus: '等待数据...',
            lastDataHash: ''
        };
    },

    watch: {
        chartData: {
            immediate: true, // 立即执行一次
            handler(newData) {
                console.log('📡 SuccessChart 数据更新:', newData);
                
                if (!this.mountedReady) {
                    console.log('组件未就绪，等待 mounted');
                    return;
                }
                
                // 检查数据是否有效
                const hasData = this.checkDataHasContent(newData);
                console.log('数据有效性检查:', hasData ? '有数据' : '无数据');
                
                if (!hasData) {
                    this.showPlaceholder = true;
                    this.chartStatus = '等待数据...';
                    return;
                }
                
                // 计算数据哈希，检查是否真的变化了
                const newHash = this.calculateDataHash(newData);
                console.log('数据哈希:', newHash.substring(0, 20) + '...');
                
                if (newHash === this.lastDataHash && this.chart) {
                    console.log('数据未变化，跳过更新');
                    return;
                }
                
                this.lastDataHash = newHash;
                this.showPlaceholder = false;
                this.chartStatus = '更新图表...';
                
                // 使用 $nextTick 确保 DOM 更新完成
                this.$nextTick(() => {
                    if (!this.chart) {
                        console.log('图表未初始化，初始化图表');
                        this.initChart(newData);
                    } else {
                        console.log('图表已存在，更新图表');
                        this.updateChart(newData);
                    }
                });
            }
        }
    },

    methods: {
        checkDataHasContent(data) {
            if (!data || typeof data !== 'object') {
                return false;
            }
            
            // 检查是否有任何适配器有数据
            return Object.values(data).some(adapterData => {
                return Array.isArray(adapterData) && adapterData.length > 0;
            });
        },
        
        calculateDataHash(data) {
            if (!data) return '';
            
            // 简单的哈希计算
            const hashData = {};
            Object.entries(data).forEach(([adapter, points]) => {
                if (Array.isArray(points) && points.length > 0) {
                    hashData[adapter] = points.slice(-5); // 只取最后5个点计算哈希
                }
            });
            
            return JSON.stringify(hashData);
        },

        buildDatasets(raw) {
            console.log('🔨 SuccessChart 构建数据集, 输入类型:', typeof raw, '内容:', raw);
            
            if (!raw || typeof raw !== 'object') {
                console.warn('输入数据无效');
                return [];
            }
            
            // 转换为普通对象
            const data = JSON.parse(JSON.stringify(raw));
            console.log('转换后数据:', data);
            
            const colors = {
                binance: '#f0b90b',
                polymarket: '#8b5cf6',
                default: '#3b82f6'
            };

            const datasets = [];
            
            Object.entries(data).forEach(([adapterName, adapterData]) => {
                console.log(`  处理适配器 ${adapterName}:`, adapterData);
                
                if (!Array.isArray(adapterData) || adapterData.length === 0) {
                    console.log(`  ⚠️ ${adapterName}: 数据不是数组或为空`);
                    return;
                }
                
                console.log(`  ✅ ${adapterName}: 有 ${adapterData.length} 个数据点`);
                
                // 处理每个数据点，确保格式正确
                const processedData = adapterData.map((point, index) => {
                    if (point && typeof point === 'object') {
                        // 确保有 x 和 y 属性
                        return {
                            x: point.x || index,
                            y: point.y || 0
                        };
                    }
                    // 如果是数字，使用索引作为 x
                    return { x: index, y: point || 0 };
                });
                
                console.log(`  ${adapterName} 处理后的数据:`, processedData.slice(0, 3)); // 显示前3个点
                
                datasets.push({
                    label: adapterName,
                    data: processedData,
                    borderColor: colors[adapterName] || colors.default,
                    backgroundColor: 'transparent',
                    borderWidth: 2,
                    tension: 0.4,
                    fill: false,
                    pointRadius: 3,
                    pointHoverRadius: 5,
                    pointBackgroundColor: colors[adapterName] || colors.default
                });
            });
            
            console.log(`✅ 构建完成: ${datasets.length} 个数据集`);
            return datasets;
        },

        initChart(data) {
            console.log('🎨 SuccessChart 初始化图表');
            
            const canvas = this.$refs.chartCanvas;
            if (!canvas) {
                console.error('❌ 找不到 canvas 元素');
                return;
            }

            // 如果已有图表，先销毁
            if (this.chart) {
                console.log('销毁旧图表');
                this.chart.destroy();
            }

            const datasets = this.buildDatasets(data);
            
            if (datasets.length === 0) {
                console.warn('没有有效数据，不初始化图表');
                this.showPlaceholder = true;
                this.chartStatus = '无有效数据';
                return;
            }

            const ctx = canvas.getContext('2d');
            
            try {
                this.chart = new Chart(ctx, {
                    type: 'line',
                    data: { datasets },
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                        animation: {
                            duration: 0 // 禁用动画
                        },
                        scales: {
                            x: {
                                type: 'linear',
                                title: {
                                    display: true,
                                    text: '时间 (s)'
                                },
                                grid: {
                                    display: true,
                                    color: 'rgba(0, 0, 0, 0.1)'
                                }
                            },
                            y: {
                                min: 0,
                                max: 100,
                                title: {
                                    display: true,
                                    text: '成功率 (%)'
                                },
                                grid: {
                                    display: true,
                                    color: 'rgba(0, 0, 0, 0.1)'
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
                        }
                    }
                });
                
                console.log('✅ 图表初始化成功');
                this.showPlaceholder = false;
                this.chartStatus = '图表就绪';
                
            } catch (error) {
                console.error('❌ 图表初始化失败:', error);
                this.showPlaceholder = true;
                this.chartStatus = '初始化失败';
            }
        },

        updateChart(data) {
            console.log('🔄 SuccessChart 更新图表数据');
            
            if (!this.chart) {
                console.warn('图表不存在，重新初始化');
                this.initChart(data);
                return;
            }
            
            const newDatasets = this.buildDatasets(data);
            
            if (newDatasets.length === 0) {
                console.warn('没有有效数据，显示占位符');
                this.showPlaceholder = true;
                return;
            }
            
            try {
                this.chart.data.datasets = newDatasets;
                this.chart.update('none');
                console.log('✅ 图表更新成功');
                this.showPlaceholder = false;
                this.chartStatus = '数据更新成功';
            } catch (error) {
                console.error('❌ 图表更新失败:', error);
                // 如果更新失败，重新初始化
                this.initChart(data);
            }
        }
    },

    mounted() {
        console.log('🚀 SuccessChart 组件挂载完成');
        this.mountedReady = true;
        
        // 如果初始有数据，立即初始化图表
        if (this.checkDataHasContent(this.chartData)) {
            console.log('初始有数据，立即初始化图表');
            this.$nextTick(() => {
                this.initChart(this.chartData);
            });
        } else {
            console.log('初始无数据，等待数据更新');
        }
    },

    beforeUnmount() {
        console.log('🗑️ SuccessChart 销毁图表');
        if (this.chart) {
            this.chart.destroy();
            this.chart = null;
        }
    }
};