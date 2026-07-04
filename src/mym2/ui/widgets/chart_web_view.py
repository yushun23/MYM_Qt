"""图表 WebView 组件。

正常 GUI 使用 QWebEngineView + 本地 ECharts。测试/无显示环境使用轻量 QWidget
降级，避免 offscreen 平台启动 Chromium 子进程导致崩溃；接口保持一致。
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from PySide6.QtCore import QUrl, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QWidget

from mym2.charts import chart_html

logger = logging.getLogger('mym2.ui.widgets.chart_web_view')

_VENDOR_DIR = Path(__file__).resolve().parent.parent.parent.parent.parent / 'resources' / 'vendor'
_VENDOR_DIR = _VENDOR_DIR.resolve()
_BASE_URL = QUrl.fromLocalFile(str(_VENDOR_DIR))
_OFFSCREEN = os.environ.get('QT_QPA_PLATFORM') == 'offscreen'

if _OFFSCREEN:
    _ChartBase = QWidget
else:
    from PySide6.QtWebEngineWidgets import QWebEngineView

    _ChartBase = QWebEngineView


class ChartWebView(_ChartBase):
    """ECharts 图表视图。"""

    chart_ready = Signal()

    def __init__(
        self,
        option: dict[str, Any] | None = None,
        *,
        title: str = 'Chart',
        parent: Any = None,
    ) -> None:
        super().__init__(parent)
        self._option = option or {}
        self._title = title
        self._loaded = False
        self._pending_update: dict[str, Any] | None = None

        if _OFFSCREEN:
            self.setObjectName('chartWebViewOffscreenFallback')
            return

        self.page().setBackgroundColor(QColor('#1e1f2b'))
        self.loadFinished.connect(self._on_load_finished)
        self.setHtml(chart_html.build_chart_html(self._option, title=self._title), _BASE_URL)

    def _on_load_finished(self, ok: bool) -> None:
        if not ok:
            logger.warning('图表 HTML 加载失败: %s', self._title)
            return
        self._loaded = True
        if self._pending_update is not None:
            self.update_chart(self._pending_update)
            self._pending_update = None
        self.chart_ready.emit()

    def update_chart(self, option: dict[str, Any]) -> None:
        """使用 setOption 更新图表数据。"""
        self._option = option
        if not self._loaded:
            self._pending_update = option
            return

        if not _OFFSCREEN:
            self.page().runJavaScript(chart_html.update_chart_js(option))

    def reload_with_option(self, option: dict[str, Any]) -> None:
        """重新加载 HTML 并设置新的 option。"""
        self._option = option
        self._loaded = False
        self._pending_update = None
        if not _OFFSCREEN:
            self.setHtml(chart_html.build_chart_html(option, title=self._title), _BASE_URL)
