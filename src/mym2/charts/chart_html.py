"""图表 HTML 生成器。

使用 setHtml(local_html, local_base_url) 加载本地 echarts.min.js。
生成的 HTML 不含任何 http://、https:// 或 CDN 链接。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# 资源目录根路径
_VENDOR_DIR = Path(__file__).resolve().parent.parent.parent.parent / "resources" / "vendor"

# base_url: QWebEngineView.setHtml 第二个参数，使相对路径图片可加载
BASE_URL = _VENDOR_DIR


def _vendor_url(filename: str) -> str:
    """生成本地 file:// URL。"""
    p = (_VENDOR_DIR / filename).resolve()
    return p.as_uri()


def chart_html_template(title: str) -> str:
    """返回不含 CDN 的 HTML 模板开头。

    echarts.min.js 通过 setHtml(local_html, base_url) 中的相对路径加载。
    """
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  html, body {{ width: 100%; height: 100%; overflow: hidden; }}
  #chart {{ width: 100%; height: 100%; }}
</style>
</head>
<body>
<div id="chart"></div>
<script src="echarts.min.js"></script>
<script>
(function() {{
  var chartDom = document.getElementById('chart');
  var myChart = echarts.init(chartDom, null, {{
    renderer: 'canvas'
  }});
  var option = __OPTION_PLACEHOLDER__;

  myChart.setOption(option);

  window.addEventListener('resize', function() {{
    if (myChart && !myChart.isDisposed()) {{
      myChart.resize();
    }}
  }});

  // 暴露接口供外部更新
  window.updateChart = function(newOption, notMerge) {{
    if (myChart && !myChart.isDisposed()) {{
      myChart.setOption(newOption, notMerge !== false);
    }}
  }};

  window.resizeChart = function() {{
    if (myChart && !myChart.isDisposed()) {{
      myChart.resize();
    }}
  }};
}})();
</script>
</body>
</html>"""


def build_chart_html(
    option: dict[str, Any],
    *,
    title: str = "MYM2 Chart",
) -> str:
    """构建完整的图表 HTML。

    Args:
        option: ECharts option dict（由 option_builders.py 生成）。
        title: HTML 页面标题。

    Returns:
        完整 HTML 字符串，不含任何外部 URL。
    """
    option_json = json.dumps(option, ensure_ascii=False)
    template = chart_html_template(title)
    return template.replace("__OPTION_PLACEHOLDER__", option_json)


def update_chart_js(new_option: dict[str, Any]) -> str:
    """生成调用 updateChart 的 JavaScript。

    用于在不重新加载 HTML 的情况下更新图表数据。

    Args:
        new_option: 新的 ECharts option dict。

    Returns:
        JavaScript 字符串。
    """
    option_json = json.dumps(new_option, ensure_ascii=False)
    return f"if (typeof updateChart === 'function') {{ updateChart({option_json}); }}"
