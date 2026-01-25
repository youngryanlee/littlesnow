export function getLayoutConfig() {
    return {
        // 卡片布局
        cardsPerRow: 2,
        cardOrder: ['binance', 'polymarket'], // 卡片显示顺序
        
        // 折叠行为
        autoCollapseSymbols: true,
        defaultCollapsed: false,
        
        // 更新频率
        updateInterval: 1000,
        
        // 显示/隐藏部分
        showCharts: true,
        showTable: true,
        showStatusPanel: true,
        
        // 主题
        theme: 'light', // light, dark, auto
        cardShadow: true,
        animations: true
    };
}

// 动态更新布局配置
export function updateLayoutConfig(newConfig) {
    const config = getLayoutConfig();
    Object.assign(config, newConfig);
    return config;
}