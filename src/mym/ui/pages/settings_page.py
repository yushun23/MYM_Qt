"""SettingsPage – user and ledger settings management."""

import logging
from pathlib import Path

from PySide6.QtCore import Qt, Slot
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFontComboBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from mym.application.services.settings_service import SettingsService
from mym.infrastructure.app_config import get_config
from mym.infrastructure.database.db_manager import DatabaseManager
from mym.infrastructure.paths.app_paths import (
    get_backup_dir,
    get_data_dir,
)
from mym.ui.navigation import AppEventBus
from mym.ui.theme.theme_manager import ThemeManager, ThemeMode

logger = logging.getLogger(__name__)


class SettingsPage(QWidget):
    """Application settings center with tabs for all configuration categories."""

    def __init__(self, session_factory=None, theme: ThemeManager | None = None, parent=None):
        super().__init__(parent)
        self._session_factory = session_factory
        self._theme = theme
        self._config = get_config()
        self._setup_ui()
        self._load_settings()

    def _session(self):
        if self._session_factory:
            return self._session_factory()
        return None

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)

        tabs = QTabWidget()

        tabs.addTab(self._build_general_tab(), "通用")
        tabs.addTab(self._build_appearance_tab(), "外观")
        tabs.addTab(self._build_ledger_tab(), "账套")
        tabs.addTab(self._build_network_tab(), "网络")
        tabs.addTab(self._build_ai_tab(), "AI")
        tabs.addTab(self._build_modules_tab(), "模块")
        tabs.addTab(self._build_data_tab(), "数据")

        layout.addWidget(tabs)

    # --- General Tab ---

    def _build_general_tab(self) -> QWidget:
        w = QWidget()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        content = QWidget()
        form = QFormLayout(content)

        self._lang_combo = QComboBox()
        self._lang_combo.addItem("中文 (zh_CN)", "zh_CN")
        self._lang_combo.addItem("English (en)", "en")
        form.addRow("语言:", self._lang_combo)

        self._export_dir_edit = QLineEdit()
        self._export_dir_edit.setReadOnly(True)
        browse_btn = QPushButton("浏览...")
        browse_btn.clicked.connect(self._browse_export_dir)
        row = QHBoxLayout()
        row.addWidget(self._export_dir_edit)
        row.addWidget(browse_btn)
        form.addRow("默认导出目录:", row)

        form.addRow(QLabel(""))

        save_btn = QPushButton("保存通用设置")
        save_btn.clicked.connect(self._save_general)
        form.addRow(save_btn)

        scroll.setWidget(content)
        outer = QVBoxLayout(w)
        outer.addWidget(scroll)
        return w

    def _browse_export_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "选择导出目录")
        if path:
            self._export_dir_edit.setText(path)

    def _save_general(self) -> None:
        session = self._session()
        try:
            svc = SettingsService(self._config, session)
            svc.set_language(self._lang_combo.currentData())
            svc.set_export_dir(self._export_dir_edit.text())
            QMessageBox.information(self, "提示", "设置已保存，重启后生效。")
        finally:
            if session:
                session.close()

    # --- Appearance Tab ---

    def _build_appearance_tab(self) -> QWidget:
        w = QWidget()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        content = QWidget()
        form = QFormLayout(content)

        self._theme_combo = QComboBox()
        self._theme_combo.addItem("浅色", ThemeMode.LIGHT.value)
        self._theme_combo.addItem("深色", ThemeMode.DARK.value)
        form.addRow("主题:", self._theme_combo)

        self._font_combo = QFontComboBox()
        form.addRow("字体:", self._font_combo)

        self._font_size_spin = QSpinBox()
        self._font_size_spin.setRange(8, 36)
        self._font_size_spin.setValue(12)
        form.addRow("字号:", self._font_size_spin)

        form.addRow(QLabel(""))

        apply_btn = QPushButton("应用外观")
        apply_btn.clicked.connect(self._save_appearance)
        form.addRow(apply_btn)

        scroll.setWidget(content)
        outer = QVBoxLayout(w)
        outer.addWidget(scroll)
        return w

    def _save_appearance(self) -> None:
        if self._theme:
            mode = ThemeMode(self._theme_combo.currentData())
            self._theme.set_mode(mode)
        svc = SettingsService(self._config)
        svc.set_theme(self._theme_combo.currentData())
        svc.set_font(
            self._font_combo.currentFont().family(),
            self._font_size_spin.value(),
        )
        AppEventBus.instance().settings_changed.emit()
        QMessageBox.information(self, "提示", "外观设置已应用")

    # --- Ledger Tab ---

    def _build_ledger_tab(self) -> QWidget:
        w = QWidget()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        content = QWidget()
        form = QFormLayout(content)

        self._ledger_name_edit = QLineEdit()
        form.addRow("账套名称:", self._ledger_name_edit)

        self._currency_combo = QComboBox()
        self._currency_combo.addItems(["CNY", "USD", "EUR", "JPY", "GBP", "HKD"])
        form.addRow("默认币种:", self._currency_combo)

        self._auto_backup_check = QCheckBox("启用自动备份")
        form.addRow("", self._auto_backup_check)

        self._backup_interval_spin = QSpinBox()
        self._backup_interval_spin.setRange(1, 90)
        self._backup_interval_spin.setValue(7)
        form.addRow("备份间隔(天):", self._backup_interval_spin)

        self._max_backup_spin = QSpinBox()
        self._max_backup_spin.setRange(1, 100)
        self._max_backup_spin.setValue(10)
        form.addRow("最大备份数:", self._max_backup_spin)

        form.addRow(QLabel(""))

        save_btn = QPushButton("保存账套设置")
        save_btn.clicked.connect(self._save_ledger)
        form.addRow(save_btn)

        scroll.setWidget(content)
        outer = QVBoxLayout(w)
        outer.addWidget(scroll)
        return w

    def _save_ledger(self) -> None:
        session = self._session()
        if not session:
            QMessageBox.warning(self, "错误", "请先打开账本")
            return
        try:
            svc = SettingsService(self._config, session)
            svc.set_ledger_name(self._ledger_name_edit.text())
            svc.set_currency(self._currency_combo.currentText())
            svc.set_auto_backup(
                self._auto_backup_check.isChecked(),
                self._backup_interval_spin.value(),
                self._max_backup_spin.value(),
            )
            session.commit()
            QMessageBox.information(self, "提示", "账套设置已保存")
        finally:
            session.close()

    # --- Network Tab ---

    def _build_network_tab(self) -> QWidget:
        w = QWidget()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        content = QWidget()
        form = QFormLayout(content)

        self._proxy_enabled_check = QCheckBox("启用代理")
        form.addRow("", self._proxy_enabled_check)

        self._proxy_type_combo = QComboBox()
        self._proxy_type_combo.addItems(["http", "https", "socks5"])
        form.addRow("代理类型:", self._proxy_type_combo)

        self._proxy_host_edit = QLineEdit()
        self._proxy_host_edit.setPlaceholderText("127.0.0.1")
        form.addRow("代理地址:", self._proxy_host_edit)

        self._proxy_port_spin = QSpinBox()
        self._proxy_port_spin.setRange(1, 65535)
        self._proxy_port_spin.setValue(8080)
        form.addRow("代理端口:", self._proxy_port_spin)

        form.addRow(QLabel("⚠️ 代理凭据不会记录在日志中"))

        form.addRow(QLabel(""))

        save_btn = QPushButton("保存网络设置")
        save_btn.clicked.connect(self._save_network)
        form.addRow(save_btn)

        scroll.setWidget(content)
        outer = QVBoxLayout(w)
        outer.addWidget(scroll)
        return w

    def _save_network(self) -> None:
        session = self._session()
        if not session:
            return
        try:
            svc = SettingsService(self._config, session)
            svc.set_proxy(
                self._proxy_enabled_check.isChecked(),
                self._proxy_host_edit.text(),
                self._proxy_port_spin.value(),
                self._proxy_type_combo.currentText(),
            )
            session.commit()
            QMessageBox.information(self, "提示", "网络设置已保存")
        finally:
            session.close()

    # --- AI Tab ---

    def _build_ai_tab(self) -> QWidget:
        w = QWidget()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        content = QWidget()
        form = QFormLayout(content)

        info = QLabel(
            "配置AI服务以启用智能记账和查询功能。\n"
            "注意：API Key使用系统安全存储，不会明文保存在数据库中。"
        )
        info.setWordWrap(True)
        form.addRow(info)

        self._ai_provider_combo = QComboBox()
        self._ai_provider_combo.addItems(["openai", "azure", "custom"])
        form.addRow("提供商:", self._ai_provider_combo)

        self._ai_model_edit = QLineEdit()
        self._ai_model_edit.setPlaceholderText("gpt-4")
        form.addRow("模型:", self._ai_model_edit)

        self._ai_base_url_edit = QLineEdit()
        self._ai_base_url_edit.setPlaceholderText("https://api.openai.com/v1")
        form.addRow("接口地址:", self._ai_base_url_edit)

        self._ai_timeout_spin = QSpinBox()
        self._ai_timeout_spin.setRange(5, 300)
        self._ai_timeout_spin.setValue(30)
        self._ai_timeout_spin.setSuffix(" 秒")
        form.addRow("超时:", self._ai_timeout_spin)

        form.addRow(QLabel("⚠️ API Key 通过系统安全存储管理，不在此处显示"))

        form.addRow(QLabel(""))

        save_btn = QPushButton("保存AI设置")
        save_btn.clicked.connect(self._save_ai)
        form.addRow(save_btn)

        scroll.setWidget(content)
        outer = QVBoxLayout(w)
        outer.addWidget(scroll)
        return w

    def _save_ai(self) -> None:
        session = self._session()
        if not session:
            return
        try:
            svc = SettingsService(self._config, session)
            svc.set_ai_config(
                self._ai_provider_combo.currentText(),
                self._ai_model_edit.text(),
                self._ai_base_url_edit.text(),
                self._ai_timeout_spin.value(),
            )
            session.commit()
            QMessageBox.information(self, "提示", "AI设置已保存")
        finally:
            session.close()

    # --- Modules Tab ---

    def _build_modules_tab(self) -> QWidget:
        w = QWidget()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        content = QWidget()
        layout = QVBoxLayout(content)

        # Plugins
        plugin_group = QGroupBox("插件管理")
        plugin_layout = QVBoxLayout(plugin_group)

        self._plugin_list = QPlainTextEdit()
        self._plugin_list.setReadOnly(True)
        self._plugin_list.setMaximumHeight(150)
        self._plugin_list.setPlaceholderText("尚未加载任何插件")
        plugin_layout.addWidget(self._plugin_list)

        layout.addWidget(plugin_group)

        layout.addStretch()

        save_btn = QPushButton("保存模块设置")
        save_btn.clicked.connect(self._save_modules)
        layout.addWidget(save_btn)

        scroll.setWidget(content)
        outer = QVBoxLayout(w)
        outer.addWidget(scroll)
        return w

    def _save_modules(self) -> None:
        svc = SettingsService(self._config)
        AppEventBus.instance().module_visibility_changed.emit()
        QMessageBox.information(self, "提示", "模块设置已保存")

    # --- Data Tab ---

    def _build_data_tab(self) -> QWidget:
        w = QWidget()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        content = QWidget()
        layout = QVBoxLayout(content)

        tools_group = QGroupBox("数据工具")
        tools_layout = QVBoxLayout(tools_group)

        open_ledger_btn = QPushButton("打开账本目录")
        open_ledger_btn.clicked.connect(self._open_ledger_dir)
        tools_layout.addWidget(open_ledger_btn)

        open_backup_btn = QPushButton("打开备份目录")
        open_backup_btn.clicked.connect(self._open_backup_dir)
        tools_layout.addWidget(open_backup_btn)

        health_btn = QPushButton("执行健康检查")
        health_btn.clicked.connect(self._run_health_check)
        tools_layout.addWidget(health_btn)

        layout.addWidget(tools_group)

        # Health report
        report_group = QGroupBox("健康检查报告")
        report_layout = QVBoxLayout(report_group)
        self._health_report_text = QPlainTextEdit()
        self._health_report_text.setReadOnly(True)
        self._health_report_text.setMaximumHeight(200)
        report_layout.addWidget(self._health_report_text)
        layout.addWidget(report_group)

        layout.addStretch()

        scroll.setWidget(content)
        outer = QVBoxLayout(w)
        outer.addWidget(scroll)
        return w

    def _open_ledger_dir(self) -> None:
        data_dir = get_data_dir()
        if data_dir.exists():
            import subprocess
            subprocess.run(["open", str(data_dir)])
        else:
            QMessageBox.information(self, "提示", "数据目录不存在")

    def _open_backup_dir(self) -> None:
        backup_dir = get_backup_dir()
        if backup_dir.exists():
            import subprocess
            subprocess.run(["open", str(backup_dir)])
        else:
            QMessageBox.information(self, "提示", "备份目录不存在")

    def _run_health_check(self) -> None:
        session = self._session()
        if not session:
            QMessageBox.warning(self, "错误", "请先打开账本")
            return
        try:
            svc = SettingsService(self._config, session)
            report = svc.get_health_report()
            lines = [
                f"状态: {report['status']}",
                f"数据完整性: {'✓' if report['integrated'] else '✗'}",
                f"外键完整: {'✓' if report['foreign_keys'] else '✗'}",
                f"账户数: {report['accounts']}",
                f"交易数: {report['transactions']}",
            ]
            if report["issues"]:
                lines.append("\n问题:")
                for issue in report["issues"]:
                    lines.append(f"  - {issue}")
            self._health_report_text.setPlainText("\n".join(lines))
        finally:
            session.close()

    # --- Load ---

    def _load_settings(self) -> None:
        session = self._session()
        try:
            svc = SettingsService(self._config, session)
            profile = svc.get_user_settings()

            # General
            idx = self._lang_combo.findData(profile.language)
            if idx >= 0:
                self._lang_combo.setCurrentIndex(idx)
            self._export_dir_edit.setText(profile.export_dir)

            # Appearance
            idx = self._theme_combo.findData(profile.theme)
            if idx >= 0:
                self._theme_combo.setCurrentIndex(idx)
            if profile.font_family:
                self._font_combo.setCurrentFont(QFont(profile.font_family))
            self._font_size_spin.setValue(profile.font_size if profile.font_size else 12)

            # Ledger
            if session:
                self._ledger_name_edit.setText(svc.get_ledger_setting("ledger/name"))
                currency = svc.get_ledger_setting("ledger/currency", "CNY")
                idx = self._currency_combo.findText(currency)
                if idx >= 0:
                    self._currency_combo.setCurrentIndex(idx)
                self._auto_backup_check.setChecked(
                    svc.get_ledger_setting_bool("backup/enabled", True)
                )
                try:
                    self._backup_interval_spin.setValue(
                        int(svc.get_ledger_setting("backup/interval_days", "7"))
                    )
                    self._max_backup_spin.setValue(
                        int(svc.get_ledger_setting("backup/max_count", "10"))
                    )
                except ValueError:
                    pass

                # Network
                self._proxy_enabled_check.setChecked(
                    svc.get_ledger_setting_bool("proxy/enabled")
                )
                self._proxy_host_edit.setText(svc.get_ledger_setting("proxy/host"))
                try:
                    self._proxy_port_spin.setValue(
                        int(svc.get_ledger_setting("proxy/port", "8080"))
                    )
                except ValueError:
                    pass
                proxy_type = svc.get_ledger_setting("proxy/type", "http")
                idx = self._proxy_type_combo.findText(proxy_type)
                if idx >= 0:
                    self._proxy_type_combo.setCurrentIndex(idx)

                # AI
                self._ai_model_edit.setText(svc.get_ledger_setting("ai/model"))
                self._ai_base_url_edit.setText(svc.get_ledger_setting("ai/base_url"))
                try:
                    self._ai_timeout_spin.setValue(
                        int(svc.get_ledger_setting("ai/timeout", "30"))
                    )
                except ValueError:
                    pass
                idx = self._ai_provider_combo.findText(
                    svc.get_ledger_setting("ai/provider", "openai")
                )
                if idx >= 0:
                    self._ai_provider_combo.setCurrentIndex(idx)

            # Modules
            if profile.plugins_enabled:
                self._plugin_list.setPlainText(
                    "\n".join(profile.plugins_enabled)
                )

        finally:
            if session:
                session.close()

    def on_enter(self) -> None:
        self._load_settings()

    def on_leave(self) -> None:
        pass
