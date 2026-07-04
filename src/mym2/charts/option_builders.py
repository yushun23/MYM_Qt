"""ECharts option JSON 构建器。

所有方法返回纯 Python dict/list，由 chart_html.py 序列化为 JSON 嵌入 HTML。
禁止 pyecharts render()；禁止 CDN 引用。
"""

from __future__ import annotations

from typing import Any


def build_asset_liability_pie(
    asset_labels: list[str],
    asset_values: list[int],
    liability_labels: list[str],
    liability_values: list[int],
    *,
    dark_mode: bool = True,
) -> dict[str, Any]:
    """资产负债构成饼图。

    左侧饼图：资产；右侧饼图：负债。
    投资快照纳入资产，但不展示股票名称/行情。

    Args:
        asset_labels: 资产账户名称列表。
        asset_values: 资产账户余额（分）。
        liability_labels: 负债账户名称列表。
        liability_values: 负债账户余额（分，正数表示欠款额）。
        dark_mode: 是否深色主题。

    Returns:
        ECharts option dict。
    """
    text_color = "#ddd" if dark_mode else "#333"

    def _to_yuan(minor: int) -> str:
        return f"{minor / 100:.2f}"

    return {
        "tooltip": {
            "trigger": "item",
            "formatter": "{b}: ¥{c} ({d}%)",
        },
        "legend": {
            "orient": "vertical",
            "left": "left",
            "textStyle": {"color": text_color},
        },
        "series": [
            {
                "name": "资产构成",
                "type": "pie",
                "radius": ["40%", "65%"],
                "center": ["30%", "55%"],
                "avoidLabelOverlap": False,
                "itemStyle": {
                    "borderRadius": 4,
                    "borderColor": "#1e1f2b" if dark_mode else "#fff",
                    "borderWidth": 2,
                },
                "label": {
                    "show": True,
                    "formatter": "{b}\n¥{c}",
                    "color": text_color,
                },
                "data": [
                    {"name": lbl, "value": _to_yuan(val)}
                    for lbl, val in zip(asset_labels, asset_values, strict=False)
                ],
            },
            {
                "name": "负债构成",
                "type": "pie",
                "radius": ["40%", "65%"],
                "center": ["70%", "55%"],
                "avoidLabelOverlap": False,
                "itemStyle": {
                    "borderRadius": 4,
                    "borderColor": "#1e1f2b" if dark_mode else "#fff",
                    "borderWidth": 2,
                },
                "label": {
                    "show": True,
                    "formatter": "{b}\n¥{c}",
                    "color": text_color,
                },
                "data": [
                    {"name": lbl, "value": _to_yuan(val)}
                    for lbl, val in zip(liability_labels, liability_values, strict=False)
                ],
            },
        ],
    }


def build_monthly_income_expense_bar(
    months: list[str],
    income_values: list[int],
    expense_values: list[int],
    *,
    dark_mode: bool = True,
) -> dict[str, Any]:
    """月度收支柱状图。

    Args:
        months: 月份标签列表（如 ["1月", "2月", ...]）。
        income_values: 每月收入总额（分）。
        expense_values: 每月支出总额（分）。
        dark_mode: 是否深色主题。

    Returns:
        ECharts option dict。
    """
    text_color = "#ddd" if dark_mode else "#333"
    axis_color = "#555" if dark_mode else "#ccc"
    split_color = "#333" if dark_mode else "#eee"

    def _to_yuan(minor: int) -> float:
        return minor / 100

    return {
        "tooltip": {
            "trigger": "axis",
            "axisPointer": {"type": "shadow"},
        },
        "legend": {
            "data": ["收入", "支出"],
            "textStyle": {"color": text_color},
            "top": 0,
        },
        "grid": {
            "left": "3%",
            "right": "4%",
            "bottom": "8%",
            "top": "15%",
            "containLabel": True,
        },
        "xAxis": {
            "type": "category",
            "data": months,
            "axisLabel": {"color": text_color},
            "axisLine": {"lineStyle": {"color": axis_color}},
            "axisTick": {"show": False},
        },
        "yAxis": {
            "type": "value",
            "axisLabel": {
                "color": text_color,
                "formatter": "{value}",
            },
            "splitLine": {"lineStyle": {"color": split_color}},
        },
        "series": [
            {
                "name": "收入",
                "type": "bar",
                "data": [_to_yuan(v) for v in income_values],
                "itemStyle": {"color": "#98c379", "borderRadius": [4, 4, 0, 0]},
                "barMaxWidth": 30,
            },
            {
                "name": "支出",
                "type": "bar",
                "data": [_to_yuan(v) for v in expense_values],
                "itemStyle": {"color": "#e06c75", "borderRadius": [4, 4, 0, 0]},
                "barMaxWidth": 30,
            },
        ],
    }


def build_net_worth_trend_line(
    months: list[str],
    net_worth_values: list[int],
    *,
    dark_mode: bool = True,
) -> dict[str, Any]:
    """净资产趋势折线图。

    Args:
        months: 月份标签列表。
        net_worth_values: 每月净资产（分）。
        dark_mode: 是否深色主题。

    Returns:
        ECharts option dict。
    """
    text_color = "#ddd" if dark_mode else "#333"
    axis_color = "#555" if dark_mode else "#ccc"
    split_color = "#333" if dark_mode else "#eee"

    def _to_yuan(minor: int) -> float:
        return minor / 100

    return {
        "tooltip": {
            "trigger": "axis",
        },
        "grid": {
            "left": "3%",
            "right": "4%",
            "bottom": "8%",
            "top": "8%",
            "containLabel": True,
        },
        "xAxis": {
            "type": "category",
            "data": months,
            "boundaryGap": False,
            "axisLabel": {"color": text_color},
            "axisLine": {"lineStyle": {"color": axis_color}},
            "axisTick": {"show": False},
        },
        "yAxis": {
            "type": "value",
            "axisLabel": {
                "color": text_color,
                "formatter": "{value}",
            },
            "splitLine": {"lineStyle": {"color": split_color}},
        },
        "series": [
            {
                "name": "净资产",
                "type": "line",
                "data": [_to_yuan(v) for v in net_worth_values],
                "smooth": True,
                "lineStyle": {"color": "#4a6cf7", "width": 3},
                "itemStyle": {"color": "#4a6cf7"},
                "areaStyle": {
                    "color": {
                        "type": "linear",
                        "x": 0, "y": 0, "x2": 0, "y2": 1,
                        "colorStops": [
                            {"offset": 0, "color": "rgba(74,108,247,0.3)"},
                            {"offset": 1, "color": "rgba(74,108,247,0.02)"},
                        ],
                    }
                },
            }
        ],
    }


def build_category_pie(
    labels: list[str],
    values: list[int],
    title: str = "支出分类",
    *,
    dark_mode: bool = True,
) -> dict[str, Any]:
    """分类饼图（用于预算概览等）。

    Args:
        labels: 分类名称列表。
        values: 分类金额（分）。
        title: 图表标题。
        dark_mode: 是否深色主题。

    Returns:
        ECharts option dict。
    """
    text_color = "#ddd" if dark_mode else "#333"

    def _to_yuan(minor: int) -> str:
        return f"{minor / 100:.2f}"

    return {
        "title": {
            "text": title,
            "left": "center",
            "top": 8,
            "textStyle": {"color": text_color, "fontSize": 14},
        },
        "tooltip": {
            "trigger": "item",
            "formatter": "{b}: ¥{c} ({d}%)",
        },
        "series": [
            {
                "type": "pie",
                "radius": ["40%", "70%"],
                "center": ["50%", "55%"],
                "avoidLabelOverlap": False,
                "itemStyle": {
                    "borderRadius": 4,
                    "borderColor": "#1e1f2b" if dark_mode else "#fff",
                    "borderWidth": 2,
                },
                "label": {
                    "show": True,
                    "color": text_color,
                    "formatter": "{b}: {d}%",
                },
                "data": [
                    {"name": lbl, "value": _to_yuan(val)}
                    for lbl, val in zip(labels, values, strict=False)
                ],
            }
        ],
    }
