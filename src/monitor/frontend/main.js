import { createApp } from "https://unpkg.com/vue@3/dist/vue.esm-browser.js";

// 导入配置
import adapterConfig from '/static/config/adapter.js';
import { getChartConfig } from '/static/config/chart-config.js';
import { getLayoutConfig } from '/static/config/layout-config.js';

// 导入服务
import { createWebSocketService } from '/static/service/websocket-service.js';
import { createNotificationService } from '/static/service/notification-service.js';

// 导入组件
import MarketDashboard from '/static/component/MarketDashboard.js';
import AdapterCard from '/static/component/AdapterCard.js';
import LatencyChart from '/static/component/LatencyChart.js';
import SuccessChart from '/static/component/SuccessChart.js';
import MetricsTable from '/static/component/MetricsTable.js';
import StatusPanel from '/static/component/StatusPanel.js';


// 创建全局配置对象
const globalConfig = {
    adapters: adapterConfig,
    charts: getChartConfig(),
    layout: getLayoutConfig()
};

// 创建服务
const websocketService = createWebSocketService();
const notificationService = createNotificationService();

// 创建Vue应用
const app = createApp(MarketDashboard);

// 全局提供配置和服务
app.provide('config', globalConfig);
app.provide('websocket', websocketService);
app.provide('notification', notificationService);

// 全局注册组件
app.component('AdapterCard', AdapterCard);
app.component('LatencyChart', LatencyChart);
app.component('SuccessChart', SuccessChart);
app.component('MetricsTable', MetricsTable);
app.component('StatusPanel', StatusPanel);

// 挂载
app.mount('#app');

// 导出供调试
window.marketDashboardApp = app;