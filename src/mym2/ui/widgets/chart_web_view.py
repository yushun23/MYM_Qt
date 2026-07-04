"""图表 WebView 组件。

QWebEngineView + 本地 ECharts 集成。
一个视图只初始化一次 ECharts 实例；刷新用 setOption；resize 调用 chart.resize()。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from PySide6.QtCore import QUrl, Signal
from PySide6.QtGui import QColor
from PySide6.QtWebEngineWidgets import QWebEngineView

from mym2.charts import chart_html

logger = logging.getLogger("mym2.ui.widgets.chart_web_view")

# 资源 vendor 目录的 file:// URL
_VENDOR_DIR = Path(__file__).resolve().parent.parent.parent.parent.parent / "resources" / "vendor"
_VENDOR_DIR = _VENDOR_DIR.resolve()
_BASE_URL = QUrl.fromLocalFile(str(_VENDOR_DIR))


class ChartWebView(QWebEngineView):
    """ECharts 图表视图。

    通过 setHtml(html, baseUrl) 加载本地 echarts.min.js。
    刷新数据时通过 runJavaScript 调用 updateChart()，不重新加载页面。

    Signals:
        chart_ready: HTML 加载完毕（loadFinished True）时发射。
    """

    chart_ready = Signal()

    def __init__(
        self,
        option: dict[str, Any] | None = None,
        *,
        title: str = "Chart",
        parent: Any = None,
    ) -> None:
        super().__init__(parent)
        self._option = option or {}
        self._title = title
        self._loaded = False
        self._pending_update: dict[str, Any] | None = None

        # 设置背景透明/深色
        self.page().setBackgroundColor(
            QColor("#1e1f2b")
        )

        self.loadFinished.connect(self._on_load_finished)

        # 加载初始 HTML
        html = chart_html.build_chart_html(self._option, title=self._title)
        self.setHtml(html, _BASE_URL)

    def _on_load_finished(self, ok: bool) -> None:
        if not ok:
            logger.warning("图表 HTML 加载失败: %s", self._title)
            return
        self._loaded = True
        if self._pending_update is not None:
            self.update_chart(self._pending_update)
            self._pending_update = None
        self.chart_ready.emit()

    def update_chart(self, option: dict[str, Any]) -> None:
        """使用 setOption 更新图表数据（不重新加载 HTML）。

        Args:
            option: 新的 ECharts option dict。
        """
        self._option = option
        if not self._loaded:
            self._pending_update = option
            return

        js = chart_html.update_chart_js(option)
        self.page().runJavaScript(js)

    def reload_with_option(self, option: dict[str, Any]) -> None:
        """重新加载 HTML 并设置新的 option。

        仅在需要更换图表类型（如 pie → bar）时使用此方法；
        一般情况下用 update_chart 更高效。

        Args:
            option: 新的 ECharts option dict。
        """
        self._option = option
        self._loaded = False
        self._pending_update = None
        html = chart_html.build_chart_html(option, title=self._title)
        self.setHtml(html, _BASE_URL)
