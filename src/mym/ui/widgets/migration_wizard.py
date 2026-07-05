"""MigrationWizard – guided UI for old .mym migration (P37)."""

import logging
from pathlib import Path

from PySide6.QtCore import Qt, Signal, QThread
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from mym.infrastructure.migrations.legacy_scanner import LegacyScanner, ScanReport
from mym.infrastructure.migrations.legacy_migrator import LegacyMigrator, MigrationResult

logger = logging.getLogger(__name__)


class ScanWorker(QThread):
    """Background worker for scanning old .mym files."""
    finished = Signal(object)  # ScanReport
    error = Signal(str)

    def __init__(self, file_path: str):
        super().__init__()
        self._file_path = file_path

    def run(self) -> None:
        try:
            scanner = LegacyScanner(self._file_path)
            report = scanner.scan()
            self.finished.emit(report)
        except Exception as e:
            self.error.emit(str(e))


class MigrateWorker(QThread):
    """Background worker for executing migration."""
    finished = Signal(object)  # MigrationResult
    error = Signal(str)

    def __init__(self, session_factory, file_path: str, sections: list[str]):
        super().__init__()
        self._session_factory = session_factory
        self._file_path = file_path
        self._sections = sections

    def run(self) -> None:
        session = self._session_factory()
        try:
            migrator = LegacyMigrator(session)
            result = migrator.migrate(self._file_path, self._sections)
            self.finished.emit(result)
        except Exception as e:
            self.error.emit(str(e))
        finally:
            session.close()


class MigrationWizard(QDialog):
    """Wizard dialog for migrating old .mym databases.

    Steps:
    1. Select file
    2. Scan & preview
    3. Choose sections
    4. Execute & report
    5. Rollback (optional)
    """

    migration_complete = Signal(object)  # MigrationResult

    def __init__(self, session_factory=None, parent=None):
        super().__init__(parent)
        self._session_factory = session_factory
        self._file_path: str | None = None
        self._scan_report: ScanReport | None = None
        self._migration_result: MigrationResult | None = None
        self._scan_worker: ScanWorker | None = None
        self._migrate_worker: MigrateWorker | None = None

        self.setWindowTitle("旧账本迁移向导")
        self.setMinimumSize(600, 500)
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)

        # Step indicator
        self._step_label = QLabel("步骤 1/4: 选择旧账本文件")
        self._step_label.setStyleSheet("font-size: 14px; font-weight: bold;")
        layout.addWidget(self._step_label)

        # Stacked pages
        self._stack = QStackedWidget()
        self._stack.addWidget(self._build_step1())
        self._stack.addWidget(self._build_step2())
        self._stack.addWidget(self._build_step3())
        self._stack.addWidget(self._build_step4())
        layout.addWidget(self._stack)

        # Progress bar
        self._progress = QProgressBar()
        self._progress.setRange(0, 0)  # indeterminate
        self._progress.setVisible(False)
        layout.addWidget(self._progress)

        # Buttons
        self._btn_box = QDialogButtonBox()
        self._back_btn = QPushButton("上一步")
        self._next_btn = QPushButton("下一步")
        self._cancel_btn = QPushButton("取消")
        self._btn_box.addButton(self._back_btn, QDialogButtonBox.ButtonRole.ActionRole)
        self._btn_box.addButton(self._next_btn, QDialogButtonBox.ButtonRole.AcceptRole)
        self._btn_box.addButton(self._cancel_btn, QDialogButtonBox.ButtonRole.RejectRole)

        self._back_btn.clicked.connect(self._on_back)
        self._next_btn.clicked.connect(self._on_next)
        self._cancel_btn.clicked.connect(self.reject)
        layout.addWidget(self._btn_box)

        self._update_buttons()

    # ── Step 1: File Selection ─────────────────────────────────────

    def _build_step1(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        info = QLabel(
            "此向导将帮助您将旧版 MYM 账本 (.mym) 迁移到新版格式。\n\n"
            "⚠️ 重要提示:\n"
            "• 迁移前会自动备份旧账本\n"
            "• 旧账本不会被修改（只读扫描）\n"
            "• 迁移后可回滚\n"
            "• 请确保旧账本未被其他程序打开"
        )
        info.setWordWrap(True)
        info.setStyleSheet("padding: 12px; background: #FFF3E0; border-radius: 4px;")
        layout.addWidget(info)

        layout.addSpacing(20)

        file_group = QGroupBox("选择旧账本文件")
        file_layout = QVBoxLayout(file_group)

        self._file_label = QLabel("未选择文件")
        self._file_label.setStyleSheet("color: #888; font-style: italic;")
        file_layout.addWidget(self._file_label)

        browse_btn = QPushButton("浏览...")
        browse_btn.clicked.connect(self._on_browse)
        file_layout.addWidget(browse_btn)

        layout.addWidget(file_group)
        layout.addStretch()

        return page

    # ── Step 2: Scan Results ───────────────────────────────────────

    def _build_step2(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        self._scan_text = QTextEdit()
        self._scan_text.setReadOnly(True)
        self._scan_text.setStyleSheet("font-family: monospace; font-size: 12px;")
        layout.addWidget(self._scan_text)

        self._scan_warning = QLabel("")
        self._scan_warning.setWordWrap(True)
        self._scan_warning.setStyleSheet("color: #D32F2F; font-weight: bold;")
        layout.addWidget(self._scan_warning)

        return page

    # ── Step 3: Section Selection ──────────────────────────────────

    def _build_step3(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        info = QLabel("选择要迁移的数据类型。建议全选以确保数据完整。")
        info.setWordWrap(True)
        layout.addWidget(info)

        sections_group = QGroupBox("迁移内容")
        sections_layout = QVBoxLayout(sections_group)

        self._chk_accounts = QCheckBox("账户和余额")
        self._chk_accounts.setChecked(True)
        sections_layout.addWidget(self._chk_accounts)

        self._chk_categories = QCheckBox("分类")
        self._chk_categories.setChecked(True)
        sections_layout.addWidget(self._chk_categories)

        self._chk_transactions = QCheckBox("交易流水")
        self._chk_transactions.setChecked(True)
        sections_layout.addWidget(self._chk_transactions)

        self._chk_receivables = QCheckBox("应收/垫付记录")
        self._chk_receivables.setChecked(True)
        sections_layout.addWidget(self._chk_receivables)

        self._chk_budgets = QCheckBox("预算数据")
        self._chk_budgets.setChecked(True)
        sections_layout.addWidget(self._chk_budgets)

        self._chk_stocks = QCheckBox("历史投资归档（只读快照）")
        self._chk_stocks.setChecked(True)
        sections_layout.addWidget(self._chk_stocks)

        self._chk_ai = QCheckBox("AI 对话历史")
        self._chk_ai.setChecked(True)
        sections_layout.addWidget(self._chk_ai)

        layout.addWidget(sections_group)

        confirm_note = QLabel(
            "⚠️ 确认后将立即开始迁移。请确保已备份旧账本。\n"
            "迁移过程不可中断，请耐心等待。"
        )
        confirm_note.setWordWrap(True)
        confirm_note.setStyleSheet("color: #E65100; padding: 8px; background: #FFF3E0; border-radius: 4px;")
        layout.addWidget(confirm_note)

        layout.addStretch()
        return page

    # ── Step 4: Results ────────────────────────────────────────────

    def _build_step4(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        self._result_label = QLabel("")
        self._result_label.setStyleSheet("font-size: 16px; font-weight: bold;")
        self._result_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._result_label)

        self._result_text = QTextEdit()
        self._result_text.setReadOnly(True)
        self._result_text.setStyleSheet("font-family: monospace; font-size: 12px;")
        layout.addWidget(self._result_text)

        btn_layout = QHBoxLayout()
        self._rollback_btn = QPushButton("回滚迁移")
        self._rollback_btn.setStyleSheet("QPushButton { background-color: #D32F2F; color: white; }")
        self._rollback_btn.clicked.connect(self._on_rollback)
        self._rollback_btn.setVisible(False)
        btn_layout.addWidget(self._rollback_btn)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        return page

    # ── Navigation ────────────────────────────────────────────────

    def _update_buttons(self) -> None:
        step = self._stack.currentIndex()
        self._back_btn.setEnabled(step > 0 and step < 3)
        self._next_btn.setEnabled(True)

        if step == 0:
            self._next_btn.setText("扫描 →")
            self._next_btn.setEnabled(self._file_path is not None)
        elif step == 1:
            self._next_btn.setText("选择内容 →")
            self._next_btn.setEnabled(
                self._scan_report is not None and self._scan_report.is_migratable()
            )
        elif step == 2:
            self._next_btn.setText("开始迁移 →")
        elif step == 3:
            self._back_btn.setVisible(False)
            self._next_btn.setText("完成")
            self._next_btn.clicked.disconnect()
            self._next_btn.clicked.connect(self.accept)

    def _on_back(self) -> None:
        self._stack.setCurrentIndex(self._stack.currentIndex() - 1)
        self._update_buttons()

    def _on_next(self) -> None:
        step = self._stack.currentIndex()

        if step == 0:
            self._start_scan()
        elif step == 1:
            self._stack.setCurrentIndex(2)
            self._update_buttons()
        elif step == 2:
            self._start_migration()

    # ── File Selection ────────────────────────────────────────────

    def _on_browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "选择旧 MYM 账本", "",
            "MYM 账本 (*.mym *.sqlite *.db);;所有文件 (*)",
        )
        if path:
            self._file_path = path
            self._file_label.setText(Path(path).name)
            self._update_buttons()

    # ── Scanning ──────────────────────────────────────────────────

    def _start_scan(self) -> None:
        self._progress.setVisible(True)
        self._next_btn.setEnabled(False)
        self._step_label.setText("正在扫描旧账本...")

        self._scan_worker = ScanWorker(self._file_path)
        self._scan_worker.finished.connect(self._on_scan_complete)
        self._scan_worker.error.connect(self._on_scan_error)
        self._scan_worker.start()

    def _on_scan_complete(self, report: ScanReport) -> None:
        self._scan_report = report
        self._progress.setVisible(False)

        self._scan_text.setPlainText(report.summary())
        if not report.is_migratable():
            self._scan_warning.setText(
                "迁移无法继续: " + "; ".join(report.errors)
            )
        elif report.warnings:
            self._scan_warning.setText(
                f"⚠️ 扫描完成，共 {len(report.warnings)} 条警告。请检查后再继续。"
            )

        self._stack.setCurrentIndex(1)
        self._step_label.setText("步骤 2/4: 扫描结果")
        self._update_buttons()

    def _on_scan_error(self, error: str) -> None:
        self._progress.setVisible(False)
        QMessageBox.critical(self, "扫描失败", f"扫描旧账本时出错:\n{error}")
        self._next_btn.setEnabled(True)

    # ── Migration ─────────────────────────────────────────────────

    def _start_migration(self) -> None:
        # Confirm
        reply = QMessageBox.question(
            self, "确认迁移",
            "即将开始数据迁移。此操作不可撤销（但可回滚）。\n\n"
            "确认要继续吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        sections = []
        if self._chk_accounts.isChecked():
            sections.append("accounts")
        if self._chk_categories.isChecked():
            sections.append("categories")
        if self._chk_transactions.isChecked():
            sections.append("transactions")
        if self._chk_receivables.isChecked():
            sections.append("receivables")
        if self._chk_budgets.isChecked():
            sections.append("budgets")
        if self._chk_stocks.isChecked():
            sections.append("stocks")
        if self._chk_ai.isChecked():
            sections.append("ai")

        self._progress.setVisible(True)
        self._next_btn.setEnabled(False)
        self._back_btn.setEnabled(False)
        self._step_label.setText("正在迁移数据...")

        self._migrate_worker = MigrateWorker(
            self._session_factory, self._file_path, sections
        )
        self._migrate_worker.finished.connect(self._on_migrate_complete)
        self._migrate_worker.error.connect(self._on_migrate_error)
        self._migrate_worker.start()

    def _on_migrate_complete(self, result: MigrationResult) -> None:
        self._migration_result = result
        self._progress.setVisible(False)

        self._result_label.setText(
            "✅ 迁移完成！" if result.success else "❌ 迁移失败"
        )
        self._result_text.setPlainText(result.summary())

        if result.errors:
            self._result_text.append(f"\n\n错误详情:\n" + "\n".join(result.errors))
        if result.warnings:
            self._result_text.append(f"\n\n警告详情:\n" + "\n".join(result.warnings))

        # Show rollback button if successful and has data
        if result.success and result.import_job_id:
            self._rollback_btn.setVisible(True)

        self._stack.setCurrentIndex(3)
        self._step_label.setText("步骤 4/4: 迁移结果")
        self._update_buttons()
        self.migration_complete.emit(result)

    def _on_migrate_error(self, error: str) -> None:
        self._progress.setVisible(False)
        QMessageBox.critical(self, "迁移失败", f"迁移过程中出错:\n{error}")
        self._next_btn.setEnabled(True)
        self._back_btn.setEnabled(True)

    # ── Rollback ──────────────────────────────────────────────────

    def _on_rollback(self) -> None:
        if not self._migration_result or not self._migration_result.import_job_id:
            return

        reply = QMessageBox.warning(
            self, "确认回滚",
            "此操作将撤销本次迁移的所有数据。\n"
            "已迁移的交易将被标记为作废。\n\n"
            "确认要回滚吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        session = self._session_factory()
        try:
            migrator = LegacyMigrator(session)
            success = migrator.rollback_migration(self._migration_result.import_job_id)
            if success:
                QMessageBox.information(self, "回滚成功", "迁移数据已成功回滚。")
                self._rollback_btn.setVisible(False)
                self._result_label.setText("🔄 已回滚")
            else:
                QMessageBox.warning(self, "回滚失败", "无法回滚迁移数据。")
        except Exception as e:
            QMessageBox.critical(self, "回滚错误", f"回滚时出错:\n{e}")
        finally:
            session.close()
