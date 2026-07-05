"""Tests for P14 – ChartHost helpers and option builders."""

import json

from mym.ui.widgets.chart_host import (
    build_bar_option,
    build_empty_option,
    build_line_option,
    build_pie_option,
    escape_data,
)


class TestEscapeData:
    """Test HTML escaping for chart data."""

    def test_plain_text_unchanged(self):
        assert escape_data("hello") == "hello"

    def test_html_tags_escaped(self):
        result = escape_data("<script>alert('XSS')</script>")
        assert "<" not in result
        assert ">" not in result
        assert "script" in result

    def test_empty_string(self):
        assert escape_data("") == ""


class TestBuildBarOption:
    """Test bar chart option builder."""

    def test_basic_bar(self):
        opt = build_bar_option(["A", "B", "C"], [10, 20, 30], title="测试")
        json_str = json.dumps(opt, ensure_ascii=False)
        assert "A" in json_str
        assert "测试" in json_str
        assert opt["series"][0]["type"] == "bar"
        assert len(opt["xAxis"]["data"]) == 3

    def test_escape_in_title(self):
        opt = build_bar_option(["X"], [1], title="<script>bad</script>")
        assert "<" not in opt["title"]["text"]

    def test_x_label_y_label(self):
        opt = build_bar_option(["M"], [1], x_label="月份", y_label="金额")
        assert "月份" in opt["xAxis"]["name"]
        assert "金额" in opt["yAxis"]["name"]


class TestBuildPieOption:
    """Test pie chart option builder."""

    def test_basic_pie(self):
        data = [{"name": "餐饮", "value": 100}, {"name": "交通", "value": 50}]
        opt = build_pie_option(data, title="分类")
        assert opt["series"][0]["type"] == "pie"
        assert len(opt["series"][0]["data"]) == 2

    def test_escape_names(self):
        data = [{"name": "<bad>", "value": 1}]
        opt = build_pie_option(data)
        assert "<" not in opt["series"][0]["data"][0]["name"]


class TestBuildLineOption:
    """Test line chart option builder."""

    def test_basic_line(self):
        opt = build_line_option(
            ["Jan", "Feb"], [{"name": "收入", "data": [100, 200]}], title="趋势"
        )
        assert opt["series"][0]["type"] == "line"
        assert opt["series"][0]["smooth"] is True

    def test_multiple_series(self):
        opt = build_line_option(
            ["X"], [{"name": "A", "data": [1]}, {"name": "B", "data": [2]}]
        )
        assert len(opt["series"]) == 2
        assert len(opt["legend"]["data"]) == 2


class TestBuildEmptyOption:
    """Test empty state option."""

    def test_empty_has_flag(self):
        opt = build_empty_option("无数据")
        assert opt["_isEmpty"] is True

    def test_custom_message(self):
        opt = build_empty_option("没有记录")
        assert opt["_isEmpty"] is True
