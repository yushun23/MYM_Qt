"""MYM2 应用启动测试（pytest-qt）。"""

import sys
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from mym2.bootstrap import bootstrap
from mym2.core.paths import get_data_dir, reset_override, set_data_dir


@pytest.fixture(autouse=True)
def _clean_path_override() -> None:
    """每个测试前后重置路径覆写并使用唯一临时目录。"""
    import uuid
    tmp = Path('/tmp') / f'mym2_test_{uuid.uuid4().hex[:8]}'
    tmp.mkdir(parents=True, exist_ok=True)
    set_data_dir(tmp)
    yield
    import shutil
    reset_override()
    shutil.rmtree(tmp, ignore_errors=True)


def test_qapplication_creatable(qapp: QApplication) -> None:
    """QApplication 可以创建（pytest-qt 自动提供 qapp fixture）。"""
    assert qapp is not None
    # pytest-qt 创建的 QApplication 名称是 'pytest-qt-qapp'
    assert qapp.applicationName() in ('', 'pytest-qt-qapp')


def test_bootstrap_reuses_existing_qapp(qapp: QApplication) -> None:
    """bootstrap() 复用已有的 QApplication 而非创建新的。"""
    window = bootstrap(data_dir=Path('/tmp/mym2_test_bootstrap'), auto_migrate=False)
    try:
        assert window is not None
        app = QApplication.instance()
        assert app is qapp  # 复用同一个实例
    finally:
        window.close()


def test_main_window_has_seven_nav_items(qapp: QApplication) -> None:
    """主窗口导航栏有 7 个占位页面，不含股票相关导航。"""
    window = bootstrap(data_dir=Path('/tmp/mym2_test_nav'), auto_migrate=False)
    try:
        assert window.nav_count == 7, f'期望 7 个导航项，实际 {window.nav_count}'

        from mym2.ui.main_window import NAV_ITEMS
        nav_labels = [label for label, _, _ in NAV_ITEMS]
        banned = ['股票', '证券', '行情', '持仓', '交易', 'stock', 'invest']

        for label in nav_labels:
            for word in banned:
                assert word not in label.lower(), f'导航包含禁止词: {label}'

        expected = ['仪表盘', '流水', '账户', '应收', '预算', '报表', '设置']
        for exp in expected:
            assert any(exp in label for label in nav_labels), f'缺失导航: {exp}'
    finally:
        window.close()


def test_navigation_switches_pages(qapp: QApplication) -> None:
    """点击导航按钮可切换页面。"""
    window = bootstrap(data_dir=Path('/tmp/mym2_test_nav2'), auto_migrate=False)
    try:
        assert window.current_page_key == 'dashboard'

        window._navigate_to('accounts')
        assert window.current_page_key == 'accounts'

        window._navigate_to('reports')
        assert window.current_page_key == 'reports'

        window._navigate_to('dashboard')
        assert window.current_page_key == 'dashboard'
    finally:
        window.close()


def test_data_dir_override_works() -> None:
    """路径覆写功能正常（测试中 data_dir 已由 fixture 覆写到 /tmp）。"""
    override = Path('/tmp/mym2_test_override_dir')
    set_data_dir(override)
    assert get_data_dir() == override


def test_no_flet_import() -> None:
    """确认项目代码没有导入 Flet。"""
    import subprocess
    result = subprocess.run(
        [sys.executable, '-c', 'import mym2'],
        capture_output=True, text=True,
    )
    assert 'flet' not in result.stderr.lower()


def test_window_close_no_exception(qapp: QApplication) -> None:
    """窗口关闭不抛异常。"""
    window = bootstrap(data_dir=Path('/tmp/mym2_test_close'), auto_migrate=False)
    window.show()
    window.close()
    # 不抛异常即通过
