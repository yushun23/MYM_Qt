"""MYM2 主窗口 — QMainWindow + 左侧导航 + QStackedWidget。"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from mym2.ui.pages.accounts_page import AccountsPage
from mym2.ui.pages.budget_page import BudgetPage
from mym2.ui.pages.dashboard_page import DashboardPage
from mym2.ui.pages.receivables_page import ReceivablesPage
from mym2.ui.pages.reports_page import ReportsPage
from mym2.ui.pages.settings_page import SettingsPage
from mym2.ui.pages.transactions_page import TransactionsPage

NAV_ITEMS: list[tuple[str, str, type[QWidget]]] = [
    ('仪表盘', 'dashboard', DashboardPage),
    ('流水', 'transactions', TransactionsPage),
    ('账户', 'accounts', AccountsPage),
    ('应收', 'receivables', ReceivablesPage),
    ('预算', 'budget', BudgetPage),
    ('报表', 'reports', ReportsPage),
    ('设置', 'settings', SettingsPage),
]

NAV_STYLE = """
QPushButton {
    text-align: left;
    padding: 10px 16px;
    border: none;
    border-radius: 6px;
    font-size: 14px;
    color: #ccc;
    background: transparent;
}
QPushButton:hover {
    background: #3a3f4b;
    color: #fff;
}
QPushButton:checked {
    background: #4a6cf7;
    color: #fff;
}
"""


class MainWindow(QMainWindow):
    """MYM2 主窗口。"""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle('MYM2 — 个人记账')
        self.resize(1100, 700)
        self.setMinimumSize(800, 500)

        self._nav_buttons: list[QPushButton] = []
        self._pages: dict[str, QWidget] = {}
        self._stack = QStackedWidget()

        self._setup_ui()
        self._navigate_to('dashboard')

    def _setup_ui(self) -> None:
        """构建左侧导航 + 右侧内容区。"""
        central = QWidget()
        self.setCentralWidget(central)

        root_layout = QHBoxLayout(central)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # ── 左侧导航 ──
        nav_panel = QFrame()
        nav_panel.setFixedWidth(160)
        nav_panel.setStyleSheet('background: #2b2d3e;')
        nav_layout = QVBoxLayout(nav_panel)
        nav_layout.setContentsMargins(8, 16, 8, 16)
        nav_layout.setSpacing(4)

        title = QLabel('MYM2')
        title.setStyleSheet('color: #fff; font-size: 18px; font-weight: bold; padding: 8px;')
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        nav_layout.addWidget(title)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet('color: #444;')
        nav_layout.addWidget(sep)
        nav_layout.addSpacing(8)

        for label_text, key, _ in NAV_ITEMS:
            btn = QPushButton(label_text)
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(NAV_STYLE)
            btn.clicked.connect(lambda checked, k=key: self._navigate_to(k))
            nav_layout.addWidget(btn)
            self._nav_buttons.append(btn)

        nav_layout.addStretch()

        # 版本号
        version_label = QLabel('v0.1.0')
        version_label.setStyleSheet('color: #555; font-size: 11px; padding: 8px;')
        version_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        nav_layout.addWidget(version_label)

        # ── 右侧内容区 ──
        self._stack.setStyleSheet('background: #1e1f2b;')

        for _label_text, key, page_cls in NAV_ITEMS:
            page = page_cls()
            self._pages[key] = page
            self._stack.addWidget(page)

        root_layout.addWidget(nav_panel)
        root_layout.addWidget(self._stack)

    def _navigate_to(self, key: str) -> None:
        """切换到指定页面。"""
        page = self._pages.get(key)
        if page is None:
            return
        self._stack.setCurrentWidget(page)
        for i, (_, k, _) in enumerate(NAV_ITEMS):
            self._nav_buttons[i].setChecked(k == key)

    @property
    def current_page_key(self) -> str:
        """当前显示页面的 key。"""
        for k, p in self._pages.items():
            if p is self._stack.currentWidget():
                return k
        return ''

    @property
    def nav_count(self) -> int:
        """导航按钮数量（用于测试验证）。"""
        return len(self._nav_buttons)
