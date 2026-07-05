"""ChartHostWidget – unified QWebEngineView-based chart container with ECharts.

Provides:
- Local ECharts loading (no CDN)
- QWebChannel bridge for Python ↔ JS communication
- Theme support, resize handling, empty/error states
- PNG export (base64) and PDF export (printToPdf)
"""

import json
import logging
from html import escape as html_escape
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QObject, QUrl, Signal, Slot
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QSizePolicy, QVBoxLayout, QWidget

from mym.resources import get_echarts_js

logger = logging.getLogger(__name__)


# ── ECharts HTML template ──────────────────────────────────────────────

_CHART_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<style>
html, body, #chart {{
    margin: 0; padding: 0; width: 100%; height: 100%;
    overflow: hidden; background: transparent;
}}
#chart.loading::after {{
    content: "⏳ 加载中...";
    position: absolute; top: 50%; left: 50%;
    transform: translate(-50%, -50%);
    font-size: 16px; color: #888; z-index: 10;
}}
#chart.empty::after {{
    content: "暂无数据";
    position: absolute; top: 50%; left: 50%;
    transform: translate(-50%, -50%);
    font-size: 16px; color: #888; z-index: 10;
}}
#chart.error::after {{
    content: "⚠ 图表加载失败";
    position: absolute; top: 50%; left: 50%;
    transform: translate(-50%, -50%);
    font-size: 16px; color: #d32f2f; z-index: 10;
}}
</style>
</head>
<body>
<div id="chart"></div>
<script src="qrc:///qtwebchannel/qwebchannel.js"></script>
<script>
var chartInstance = null;
var currentOption = null;
var currentTheme = 'light';
var bridge = null;

// Helper: escape HTML entities for safe display
function safeEscape(str) {{
    if (typeof str !== 'string') return str;
    var div = document.createElement('div');
    div.appendChild(document.createTextNode(str));
    return div.innerHTML;
}}

// Theme colours
var themes = {{
    light: {{
        textColor: '#333',
        backgroundColor: 'transparent',
    }},
    dark: {{
        textColor: '#ddd',
        backgroundColor: 'transparent',
    }}
}};

function applyTheme(themeName) {{
    currentTheme = themeName;
    if (currentOption) {{
        var opt = JSON.parse(JSON.stringify(currentOption));
        var t = themes[themeName] || themes.light;
        if (opt.textStyle) opt.textStyle.color = t.textColor;
        renderChart(opt);
    }}
}}

function renderChart(option) {{
    var dom = document.getElementById('chart');
    dom.className = '';

    if (!option || !option.series || option._isEmpty) {{
        dom.className = 'empty';
        if (chartInstance) {{ chartInstance.dispose(); chartInstance = null; }}
        return;
    }}

    if (!chartInstance) {{
        chartInstance = echarts.init(dom, currentTheme);
        chartInstance.on('click', function(params) {{
            if (bridge) bridge.onChartClick(JSON.stringify(params));
        }});
        chartInstance.on('legendselectchanged', function(params) {{
            if (bridge) bridge.onLegendChanged(JSON.stringify(params));
        }});
        chartInstance.on('datazoom', function(params) {{
            if (bridge) bridge.onDataZoom(JSON.stringify(params));
        }});
    }}

    currentOption = option;
    chartInstance.setOption(option, true);
}}

function updateData(jsonData) {{
    try {{
        var option = JSON.parse(jsonData);
        renderChart(option);
    }} catch(e) {{
        document.getElementById('chart').className = 'error';
    }}
}}

function getChartImage(format) {{
    if (!chartInstance) return '';
    return chartInstance.getDataURL({{ type: format || 'png', pixelRatio: 2 }});
}}

// QWebChannel setup
new QWebChannel(qt.webChannelTransport, function(channel) {{
    bridge = channel.objects.bridge;
    if (bridge) {{
        bridge.dataUpdated.connect(function(data) {{
            updateData(data);
        }});
        bridge.themeChanged.connect(function(themeName) {{
            applyTheme(themeName);
        }});
        bridge.exportRequested.connect(function(format) {{
            var img = getChartImage(format || 'png');
            if (bridge) bridge.exportReady(img);
        }});
    }}
}});

window.addEventListener('resize', function() {{
    if (chartInstance) chartInstance.resize();
}});
</script>
</body>
</html>"""


# ── QWebChannel Bridge ─────────────────────────────────────────────────

class ChartBridge(QObject):
    """QWebChannel bridge object for Python ↔ JS communication."""

    dataUpdated = Signal(str)
    themeChanged = Signal(str)
    exportRequested = Signal(str)

    # Signals emitted *from* JS → Python
    chartClicked = Signal(str)
    legendChanged = Signal(str)
    dataZoomed = Signal(str)
    exportReady = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)

    @Slot(str)
    def onChartClick(self, params_json: str) -> None:
        """Called from JS when a chart element is clicked."""
        self.chartClicked.emit(params_json)

    @Slot(str)
    def onLegendChanged(self, params_json: str) -> None:
        """Called from JS when legend selection changes."""
        self.legendChanged.emit(params_json)

    @Slot(str)
    def onDataZoom(self, params_json: str) -> None:
        """Called from JS when data zoom changes."""
        self.dataZoomed.emit(params_json)

    @Slot(str)
    def onExportReady(self, data_url: str) -> None:
        """Called from JS with the export base64 data URL."""
        self.exportReady.emit(data_url)


# ── ChartHostWidget ────────────────────────────────────────────────────

class ChartHostWidget(QWidget):
    """Unified chart container using QWebEngineView + local ECharts.

    Usage:
        host = ChartHostWidget()
        host.set_option({"xAxis": {...}, "series": [...]})
        host.set_theme("dark")
        host.export_png()  # emits export_ready signal
    """

    chartClicked = Signal(str)   # emits JSON string of ECharts click params
    legendChanged = Signal(str)
    dataZoomed = Signal(str)
    export_ready = Signal(str)   # emits base64 data URL

    def __init__(self, parent=None):
        super().__init__(parent)
        self._bridge: Optional[ChartBridge] = None
        self._channel: Optional[QWebChannel] = None
        self._current_theme = "light"
        self._option: Optional[dict] = None
        self._data_json: str = "{}"
        self._page_loaded = False
        self._pending_loads: list[str] = []

        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._webview = QWebEngineView()
        self._webview.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )

        # Security: restrict to local resources only
        settings = self._webview.settings()
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, False)
        settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalStorageEnabled, False)
        settings.setAttribute(QWebEngineSettings.WebAttribute.ErrorPageEnabled, False)

        # Set up QWebChannel
        self._channel = QWebChannel()
        self._bridge = ChartBridge()
        self._channel.registerObject("bridge", self._bridge)
        self._webview.page().setWebChannel(self._channel)

        # Wire bridge signals
        self._bridge.chartClicked.connect(self.chartClicked)
        self._bridge.legendChanged.connect(self.legendChanged)
        self._bridge.dataZoomed.connect(self.dataZoomed)
        self._bridge.exportReady.connect(self.export_ready)

        # Load the HTML template with local echarts
        self._webview.loadFinished.connect(self._on_page_loaded)

        echarts_js_path = get_echarts_js()
        if not echarts_js_path.exists():
            logger.error("echarts.min.js not found at %s", echarts_js_path)
            self._webview.setHtml("<html><body><p>ECharts library missing</p></body></html>")
            return

        # Build HTML with inline echarts
        echarts_code = echarts_js_path.read_text(encoding="utf-8")
        html = _CHART_TEMPLATE.replace(
            '<script src="qrc:///qtwebchannel/qwebchannel.js"></script>',
            '<script>' + echarts_code + '</script>\n'
            '<script src="qrc:///qtwebchannel/qwebchannel.js"></script>'
        )

        self._webview.setHtml(html, QUrl("about:blank"))

        layout.addWidget(self._webview)

    def _on_page_loaded(self, ok: bool) -> None:
        if not ok:
            logger.error("ChartHost page failed to load")
            return
        self._page_loaded = True
        # Apply any pending updates
        for data_json in self._pending_loads:
            self._push_data(data_json)
        self._pending_loads.clear()
        if self._option is not None:
            self._push_option()

    def _push_data(self, data_json: str) -> None:
        """Push data to JS via the bridge signal."""
        if self._bridge:
            self._bridge.dataUpdated.emit(data_json)

    def _push_option(self) -> None:
        """Push Python option dict to JS."""
        if self._option is None:
            data = json.dumps({"_isEmpty": True}, ensure_ascii=False)
        else:
            data = json.dumps(self._option, ensure_ascii=False, default=str)
        self._data_json = data
        if self._page_loaded:
            self._push_data(data)
        else:
            self._pending_loads.append(data)

    # ── Public API ─────────────────────────────────────────────────────

    def set_option(self, option: Optional[dict]) -> None:
        """Set the ECharts option dict. Pass None or empty to show empty state."""
        self._option = option
        self._push_option()

    def set_data_json(self, data_json: str) -> None:
        """Set raw JSON option string directly."""
        self._data_json = data_json
        if self._page_loaded:
            self._push_data(data_json)
        else:
            self._pending_loads.append(data_json)

    def set_theme(self, theme: str) -> None:
        """Set chart theme ('light' or 'dark')."""
        self._current_theme = theme
        if self._bridge and self._page_loaded:
            self._bridge.themeChanged.emit(theme)

    def export_png(self) -> None:
        """Request PNG export. Result arrives via export_ready signal."""
        if self._bridge and self._page_loaded:
            self._bridge.exportRequested.emit("png")

    def export_pdf(self, file_path: str) -> None:
        """Export chart to PDF file using QWebEnginePage.printToPdf."""
        if not self._page_loaded:
            logger.warning("Page not loaded, cannot export PDF")
            return
        self._webview.page().printToPdf(str(file_path))

    def resize_chart(self) -> None:
        """Trigger chart resize (useful after parent resize)."""
        if self._page_loaded:
            self._webview.page().runJavaScript("if(chartInstance) chartInstance.resize();")

    def is_ready(self) -> bool:
        """Whether the page has finished loading."""
        return self._page_loaded


# ── Chart helper: build common option types ─────────────────────────────

def escape_data(data: str) -> str:
    """Escape user-supplied strings for safe inclusion in HTML/JavaScript."""
    return html_escape(data, quote=False)


def build_bar_option(
    categories: list[str],
    values: list[float],
    title: str = "",
    x_label: str = "",
    y_label: str = "",
    color: str = "#1976D2",
) -> dict:
    """Build a simple bar chart ECharts option."""
    return {
        "tooltip": {"trigger": "axis"},
        "title": {"text": escape_data(title), "left": "center", "textStyle": {"fontSize": 14}},
        "xAxis": {
            "type": "category",
            "data": [escape_data(c) for c in categories],
            "name": escape_data(x_label) if x_label else "",
        },
        "yAxis": {
            "type": "value",
            "name": escape_data(y_label) if y_label else "",
        },
        "series": [{
            "type": "bar",
            "data": values,
            "itemStyle": {"color": color},
            "barMaxWidth": 40,
        }],
    }


def build_pie_option(
    data: list[dict],  # [{"name": "", "value": 0}, ...]
    title: str = "",
    radius: str = "60%",
) -> dict:
    """Build a pie/ring chart ECharts option."""
    for item in data:
        item["name"] = escape_data(item.get("name", ""))
    return {
        "tooltip": {"trigger": "item"},
        "title": {"text": escape_data(title), "left": "center", "textStyle": {"fontSize": 14}},
        "legend": {"bottom": 5, "type": "scroll"},
        "series": [{
            "type": "pie",
            "radius": radius,
            "data": data,
            "label": {"formatter": "{b}: {d}%"},
            "emphasis": {
                "itemStyle": {"shadowBlur": 10, "shadowOffsetX": 0, "shadowColor": "rgba(0,0,0,0.5)"},
            },
        }],
    }


def build_line_option(
    x_data: list[str],
    series_list: list[dict],  # [{"name": "", "data": [...], "color": ""}, ...]
    title: str = "",
    x_label: str = "",
    y_label: str = "",
    smooth: bool = True,
) -> dict:
    """Build a line chart ECharts option."""
    safe_series = []
    for s in series_list:
        s_copy = dict(s)
        s_copy["type"] = "line"
        s_copy["smooth"] = smooth
        if "name" in s_copy:
            s_copy["name"] = escape_data(s_copy["name"])
        safe_series.append(s_copy)

    return {
        "tooltip": {"trigger": "axis"},
        "title": {"text": escape_data(title), "left": "center", "textStyle": {"fontSize": 14}},
        "legend": {"data": [escape_data(s.get("name", "")) for s in series_list], "bottom": 5},
        "xAxis": {
            "type": "category",
            "data": [escape_data(x) for x in x_data],
            "name": escape_data(x_label) if x_label else "",
        },
        "yAxis": {
            "type": "value",
            "name": escape_data(y_label) if y_label else "",
        },
        "series": safe_series,
    }


def build_empty_option(message: str = "暂无数据") -> dict:
    """Return an option that triggers the empty state in the chart host."""
    return {"_isEmpty": True}
