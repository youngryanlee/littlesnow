export default {
  binance: {
    name: "Binance",
    color: "#f0b90b",
    icon: "bi-currency-exchange",
    type: "exchange",

    metrics: {
      /* ========= 核心大指标 ========= */
      avg_latency_ms: {
        label: "平均延迟",
        unit: "ms",
        format: "number",
        decimals: 1,
        thresholds: { good: 50, warning: 100 }
      },

      success_rate: {
        label: "成功率",
        format: "percent",
        decimals: 1
      },

      /* ========= 验证 ========= */
      validations_total: {
        label: "验证次数",
        format: "number",
        group: "validation"
      },

      validations_success: {
        label: "验证通过",
        format: "number",
        group: "validation",
        color: {
          type: "static",  // 静态颜色
          value: "text-success"  // 始终显示为绿色
        }
      },

      validations_failed: {
        label: "验证失败",
        format: "number",
        group: "validation",
        color: {
          type: "static",
          value: "text-danger"  // 始终显示为红色
        }
      },

      validation_success_rate: {
        label: "验证统计",
        format: "percent",
        decimals: 1,
        group: "validation",
        // 基于阈值动态颜色
        color: {
          type: "threshold",
          thresholds: [
            { min: 0.99, class: "badge bg-success" },  // ≥99% 绿色
            { min: 0.95, class: "badge bg-warning" },  // ≥95% 黄色
            { min: 0, class: "badge bg-danger" }       // 其他 红色
          ]
        }
      },

      warnings: {
        label: "警告数",
        format: "number",
        group: "validation",
        display: "icon",  // 指定显示类型为带图标
        icon: "bi-exclamation-triangle",  // 指定图标
        color: {
          type: "conditional",
          conditions: [
            { condition: ">", value: 0, class: "text-warning" },
            { condition: "=", value: 0, class: "text-muted" }  // 0警告时显示灰色
          ]
        }
      },

      avg_pending_buffer: {
        label: "缓冲队列",
        format: "number",
        group: "validation"
      },

      /* ========= 信号 ========= */
      total_signals: {
        label: "T0信号",
        format: "number",
        group: "signals"
      },

      t0_rate: {
        label: "T0率",
        format: "percent",
        decimals: 2,
        group: "signals"
      },

      avg_signals_per_minute: {
        label: "T0/min",
        format: "number",
        decimals: 2,
        group: "signals"
      },

      avg_signal_interval: {
        label: "平均T0间隔",
        unit: "ms",
        format: "number",
        group: "signals"
      },

      avg_cooldown_interval: {
        label: "平均冷却",
        unit: "ms",
        format: "number",
        group: "signals"
      },

      up_percent: {
        label: "Up率",
        format: "percent",
        decimals: 1,
        group: "signals"
      },

      down_percent: {
        label: "Down率",
        format: "percent",
        decimals: 1,
        group: "signals"
      },

      /* ========= 最近窗口 ========= */
      recent_signals_per_minute: {
        label: "T0/min",
        format: "number",
        group: "recent"
      },

      recent_signal_interval: {
        label: "T0间隔",
        unit: "ms",
        format: "number",
        group: "recent"
      },

      recent_up_percent: {
        label: "Up率",
        format: "percent",
        group: "recent"
      },

      recent_down_percent: {
        label: "Down率",
        format: "percent",
        group: "recent"
      }
    },

    sections: [
      {
        name: "validation",
        title: "验证信息",
        icon: "bi-list-check"
      },
      {
        name: "signals",
        title: "信号统计",
        icon: "bi-graph-up-arrow"
      },
      {
        name: "recent",
        title: "最近1分钟窗口",
        icon: "bi-clock-history"
      }
    ]
  },

  polymarket: {
    name: "Polymarket",
    color: "#8b5cf6",
    icon: "bi-graph-up",
    type: "prediction_market",

    metrics: {
      avg_latency_ms: {
        label: "平均延迟",
        unit: "ms",
        format: "number",
        decimals: 1,
        thresholds: { good: 100, warning: 200 }
      },

      success_rate: {
        label: "成功率",
        format: "percent",
        decimals: 1
      },

      p50_latency_ms: {
        label: "P50 延迟",
        format: "number",
        group: "latency_distribution"
      },

      p95_latency_ms: {
        label: "P95 延迟",
        format: "number",
        group: "latency_distribution"
      },

      p99_latency_ms: {
        label: "P99 延迟",
        format: "number",
        group: "latency_distribution"
      },

      max_latency_ms: {
        label: "最大延迟",
        format: "number",
        group: "latency_distribution"
      },

      min_latency_ms: {
        label: "最小延迟",
        format: "number",
        group: "latency_distribution"
      }
    },

    sections: [
      {
        name: "latency_distribution",
        title: "延迟分布",
        icon: "bi-bar-chart"
      }
    ]
  }
};