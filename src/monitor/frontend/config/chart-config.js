export function getChartConfig() {
    return {
        latency: {
            title: "延迟趋势",
            type: "line",
            yAxis: {
                title: "延迟 (ms)",
                beginAtZero: true
            },
            xAxis: {
                title: "时间 (秒)",
                type: "linear"
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                animation: {
                    duration: 0
                }
            }
        },
        
        success: {
            title: "成功率趋势",
            type: "line",
            yAxis: {
                title: "成功率 (%)",
                min: 0,
                max: 100
            },
            xAxis: {
                title: "时间 (秒)",
                type: "linear"
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                animation: {
                    duration: 0
                }
            }
        }
    };
}

// 适配器颜色映射
export function getAdapterColor(adapterName) {
    const colors = {
        'binance': '#f0b90b',
        'polymarket': '#8b5cf6',
        'default': '#3b82f6'
    };
    return colors[adapterName] || colors.default;
}