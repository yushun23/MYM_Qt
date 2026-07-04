"""MYM2 图表模块 — 本地离线 ECharts 集成。

提供 ECharts option 构建器和 HTML 生成器。
所有图表通过本地 echarts.min.js 渲染，不含 CDN 依赖。
"""

from mym2.charts import chart_html, option_builders

__all__ = [
    "chart_html",
    "option_builders",
]
