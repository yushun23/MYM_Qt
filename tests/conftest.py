"""pytest 全局配置 — 确保 Qt 测试在无显示器环境可运行。"""

import os


def pytest_configure(config) -> None:
    """配置 Qt 使用 offscreen 平台。"""
    if 'QT_QPA_PLATFORM' not in os.environ:
        os.environ['QT_QPA_PLATFORM'] = 'offscreen'
