"""设置页面。"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from mym2.core.paths import get_backups_dir, get_db_path
from mym2.db.session import get_session
from mym2.services.backup_service import RESTORE_CONFIRMATION, BackupService
from mym2.services.settings_service import SettingsService


class SettingsPage(QWidget):
    """设置 — 非秘密偏好、备份恢复、AI 开关与历史归档入口。"""

    navigate_to = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._settings = SettingsService()
        self._backup = BackupService()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        title = QLabel('设置')
        title.setStyleSheet('font-size: 24px; font-weight: bold; color: #fff;')
        layout.addWidget(title)

        layout.addWidget(self._build_preferences_group())
        layout.addWidget(self._build_backup_group())
        layout.addWidget(self._build_ai_group())
        layout.addWidget(self._build_archive_card())
        layout.addStretch()

        self._load_settings()

    def _build_preferences_group(self) -> QGroupBox:
        group = QGroupBox('偏好')
        form = QFormLayout(group)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self._theme_combo = QComboBox()
        self._theme_combo.addItems(['dark', 'light'])
        form.addRow('主题', self._theme_combo)

        self._language_combo = QComboBox()
        self._language_combo.addItems(['zh_CN', 'en_US'])
        form.addRow('语言', self._language_combo)

        self._font_size = QSpinBox()
        self._font_size.setRange(9, 24)
        form.addRow('字号', self._font_size)

        export_row = QHBoxLayout()
        self._export_dir = QLineEdit()
        export_btn = QPushButton('选择')
        export_btn.clicked.connect(self._choose_export_dir)
        export_row.addWidget(self._export_dir)
        export_row.addWidget(export_btn)
        form.addRow('导出目录', export_row)

        save_btn = QPushButton('保存偏好')
        save_btn.clicked.connect(self._save_settings)
        form.addRow('', save_btn)
        return group

    def _build_backup_group(self) -> QGroupBox:
        group = QGroupBox('备份与恢复')
        form = QFormLayout(group)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self._backup_before_migration = QCheckBox('迁移前自动备份')
        form.addRow('', self._backup_before_migration)

        self._retention = QSpinBox()
        self._retention.setRange(1, 365)
        form.addRow('保留份数', self._retention)

        self._backup_schedule = QComboBox()
        self._backup_schedule.addItems(['manual', 'daily', 'weekly'])
        form.addRow('备份策略', self._backup_schedule)

        actions = QHBoxLayout()
        backup_btn = QPushButton('立即备份')
        restore_btn = QPushButton('恢复备份')
        backup_btn.clicked.connect(self._manual_backup)
        restore_btn.clicked.connect(self._restore_backup)
        actions.addWidget(backup_btn)
        actions.addWidget(restore_btn)
        form.addRow('', actions)
        return group

    def _build_ai_group(self) -> QGroupBox:
        group = QGroupBox('AI 助手')
        form = QFormLayout(group)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self._ai_enabled = QCheckBox('启用 AI（默认关闭，只读草稿）')
        form.addRow('', self._ai_enabled)

        self._ai_model = QLineEdit()
        form.addRow('模型', self._ai_model)

        self._ai_url = QLineEdit()
        self._ai_url.setPlaceholderText('服务 URL（不含密钥）')
        form.addRow('服务 URL', self._ai_url)
        return group

    def _build_archive_card(self) -> QFrame:
        card = QFrame()
        card.setStyleSheet(
            'QFrame { background: #252738; border-radius: 8px; padding: 16px; }'
        )
        card_layout = QVBoxLayout(card)
        card_title = QLabel('历史归档')
        card_title.setStyleSheet('font-size: 16px; font-weight: bold; color: #ddd;')
        card_layout.addWidget(card_title)

        card_desc = QLabel(
            '查看导入批次、历史证券归档摘要。\n'
            '导出归档 JSON/CSV。\n'
            '历史证券数据以只读快照保存，不提供持仓、行情等功能。'
        )
        card_desc.setStyleSheet('color: #888; font-size: 13px;')
        card_desc.setWordWrap(True)
        card_layout.addWidget(card_desc)

        btn = QPushButton('打开历史归档')
        btn.setStyleSheet(
            'QPushButton { background: #4a6cf7; color: #fff; padding: 8px 16px; '
            'border-radius: 4px; font-weight: bold; }'
            'QPushButton:hover { background: #3b5de7; }'
        )
        btn.clicked.connect(lambda: self.navigate_to.emit('history_archive'))
        card_layout.addWidget(btn, 0, Qt.AlignmentFlag.AlignLeft)
        return card

    def _load_settings(self) -> None:
        try:
            session = get_session()
            self._theme_combo.setCurrentText(
                self._settings.get(session, 'theme', 'dark') or 'dark'
            )
            self._language_combo.setCurrentText(
                self._settings.get(session, 'language', 'zh_CN') or 'zh_CN'
            )
            self._font_size.setValue(
                self._settings.get_int(session, 'font_size', 11)
            )
            self._export_dir.setText(
                self._settings.get(session, 'export_dir', '') or ''
            )
            self._backup_before_migration.setChecked(
                self._settings.get_bool(
                    session, 'backup_auto_before_migration', True
                )
            )
            self._retention.setValue(
                self._settings.get_int(session, 'backup_retention_count', 10)
            )
            self._backup_schedule.setCurrentText(
                self._settings.get(session, 'backup_schedule', 'manual') or 'manual'
            )
            self._ai_enabled.setChecked(
                self._settings.get_bool(session, 'ai_enabled', False)
            )
            self._ai_model.setText(self._settings.get(session, 'ai_model', '') or '')
            self._ai_url.setText(
                self._settings.get(session, 'ai_service_url', '') or ''
            )
        except RuntimeError:
            return

    def _save_settings(self) -> None:
        try:
            session = get_session()
            self._settings.set_many(session, {
                'theme': self._theme_combo.currentText(),
                'language': self._language_combo.currentText(),
                'font_size': str(self._font_size.value()),
                'export_dir': self._export_dir.text().strip(),
                'backup_auto_before_migration': (
                    'true' if self._backup_before_migration.isChecked() else 'false'
                ),
                'backup_retention_count': str(self._retention.value()),
                'backup_schedule': self._backup_schedule.currentText(),
                'ai_enabled': 'true' if self._ai_enabled.isChecked() else 'false',
                'ai_model': self._ai_model.text().strip(),
                'ai_service_url': self._ai_url.text().strip(),
            })
            session.commit()
            QMessageBox.information(self, '设置', '已保存')
        except Exception as exc:
            QMessageBox.warning(self, '设置', f'保存失败：{exc}')

    def _choose_export_dir(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, '选择导出目录')
        if directory:
            self._export_dir.setText(directory)

    def _manual_backup(self) -> None:
        try:
            metadata = self._backup.create_backup(
                get_db_path(),
                get_backups_dir(),
                reason='manual',
                retention_count=self._retention.value(),
            )
            QMessageBox.information(
                self,
                '备份完成',
                f'文件：{metadata.filename}\nSHA-256：{metadata.sha256}',
            )
        except Exception as exc:
            QMessageBox.warning(self, '备份失败', str(exc))

    def _restore_backup(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(
            self,
            '选择备份',
            str(get_backups_dir()),
            'SQLite DB (*.db);;All Files (*)',
        )
        if not filename:
            return
        text, ok = QInputDialog.getText(
            self,
            '确认恢复',
            f'恢复会覆盖当前数据库，并需要重启。\n请输入确认文本：{RESTORE_CONFIRMATION}',
        )
        if not ok or text != RESTORE_CONFIRMATION:
            QMessageBox.information(self, '恢复取消', '确认文本不匹配，未恢复。')
            return
        try:
            self._backup.restore_backup(
                Path(filename),
                get_db_path(),
                confirmation_text=RESTORE_CONFIRMATION,
            )
            QMessageBox.information(self, '恢复完成', '数据库已恢复，请重启应用。')
        except Exception as exc:
            QMessageBox.warning(self, '恢复失败', str(exc))
