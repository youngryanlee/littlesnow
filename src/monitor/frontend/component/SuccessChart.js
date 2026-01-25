import { markRaw } from "https://unpkg.com/vue@3/dist/vue.esm-browser.js";

export default {
    template: `
        <div class="card mb-4">
            <div class="card-header">
                <h5 class="mb-0">
                    <i class="bi bi-percent"></i> {{ title }}
                    <small v-if="showDebug" class="text-muted ms-2">
                        状态: {{ chartStatus }}
                    </small>
                </h5>
            </div>
            <div class="card-body" style="height:300px; position: relative;">
                <canvas ref="chartCanvas"></canvas>
                <div v-if="showPlaceholder"
                     class="position-absolute top-50 start-50 translate-middle text-center text-muted">
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
            immediate: true,
            handler(newData) {
                console.log('📡 SuccessChart 数据更新:', newData);

                if (!this.mountedReady) return;

                if (!this.checkDataHasContent(newData)) {
                    this.showPlaceholder = true;
                    this.chartStatus = '等待数据...';
                    return;
                }

                // 计算数据哈希，检查是否真的变化了
                const newHash = this.calculateDataHash(newData);
                if (newHash === this.lastDataHash) {
                    console.log('数据未变化，跳过');
                    return;
                }

                this.lastDataHash = newHash;
                this.chartStatus = '更新图表...';
                this.showPlaceholder = false;

                this.$nextTick(() => {
                    // ⭐ 只允许重建，禁止 update
                    this.initChart(newData);
                });
            }
        }
    },

    methods: {
        checkDataHasContent(data) {
            if (!data || typeof data !== 'object') return false;
            return Object.values(data).some(
                v => Array.isArray(v) && v.length > 0
            );
        },

        calculateDataHash(data) {
            if (!data) return '';
            const hash = {};
            Object.entries(data).forEach(([k, v]) => {
                if (Array.isArray(v) && v.length > 0) {
                    hash[k] = v.slice(-5);
                }
            });
            return JSON.stringify(hash);
        },

        buildDatasets(raw) {
            if (!raw || typeof raw !== 'object') return [];

            // ⭐ 彻底去 Vue Proxy
            const data = JSON.parse(JSON.stringify(raw));

            const colors = {
                binance: '#f0b90b',
                polymarket: '#8b5cf6',
                default: '#3b82f6'
            };

            return Object.entries(data)
                .filter(([, arr]) => Array.isArray(arr) && arr.length > 0)
                .map(([name, arr]) => ({
                    label: name,
                    data: arr.map((p, i) => ({
                        x: typeof p === 'object' ? p.x ?? i : i,
                        y: typeof p === 'object' ? p.y ?? 0 : p ?? 0
                    })),
                    borderColor: colors[name] || colors.default,
                    backgroundColor: 'transparent',
                    borderWidth: 2,
                    tension: 0.4,
                    fill: false,
                    pointRadius: 3,
                    pointHoverRadius: 5,
                    pointBackgroundColor: colors[name] || colors.default
                }));
        },

        initChart(data) {
            console.log('🎨 SuccessChart 初始化（重建模式）');

            const canvas = this.$refs.chartCanvas;
            if (!canvas) return;

            if (this.chart) {
                console.log('🗑️ 销毁旧图表');
                this.chart.destroy();
                this.chart = null;
            }

            const datasets = this.buildDatasets(data);
            if (datasets.length === 0) {
                this.showPlaceholder = true;
                this.chartStatus = '无有效数据';
                return;
            }

            const ctx = canvas.getContext('2d');

            try {
                this.chart = markRaw(new Chart(ctx, {
                    type: 'line',
                    data: { datasets },
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                        animation: false,
                        scales: {
                            x: {
                                type: 'linear',
                                title: { display: true, text: '时间 (s)' }
                            },
                            y: {
                                min: 0,
                                max: 100,
                                title: { display: true, text: '成功率 (%)' }
                            }
                        },
                        plugins: {
                            legend: { display: true },
                            tooltip: {
                                mode: 'index',
                                intersect: false,
                                callbacks: {
                                    label(ctx) {
                                        return `${ctx.dataset.label}: ${ctx.parsed.y.toFixed(1)}%`;
                                    }
                                }
                            }
                        }
                    }
                }));

                this.chartStatus = '图表就绪';
                this.showPlaceholder = false;
                console.log('✅ SuccessChart 初始化成功');

            } catch (e) {
                console.error('❌ SuccessChart 初始化失败:', e);
                this.showPlaceholder = true;
                this.chartStatus = '初始化失败';
            }
        }
    },

    mounted() {
        console.log('🚀 SuccessChart 挂载完成');
        this.mountedReady = true;

        if (this.checkDataHasContent(this.chartData)) {
            this.$nextTick(() => this.initChart(this.chartData));
        }
    },

    beforeUnmount() {
        if (this.chart) {
            this.chart.destroy();
            this.chart = null;
        }
    }
};
