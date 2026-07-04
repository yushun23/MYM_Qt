"""导入向导 — PySide6 多步骤迁移向导。"""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QStackedWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from mym2.importers.legacy_mym.audit import audit_mym_file
from mym2.importers.legacy_mym.executor import MigrationExecutor
from mym2.importers.legacy_mym.migration_plan import MigrationPlan
from mym2.importers.legacy_mym.migration_service import MigrationService

logger = logging.getLogger('mym2.ui.import_wizard')


class _AuditWorker(QThread):
    finished = Signal(object)
    error = Signal(str)

    def __init__(self, file_path: str) -> None:
        super().__init__()
        self._file_path = file_path

    def run(self) -> None:
        try:
            import tempfile
            with tempfile.TemporaryDirectory() as tmpdir:
                result = audit_mym_file(self._file_path, tmpdir)
                self.finished.emit(result)
        except Exception as e:
            self.error.emit(str(e))


class _PlanWorker(QThread):
    finished = Signal(object)
    error = Signal(str)

    def __init__(self, file_path: str, strategy: str) -> None:
        super().__init__()
        self._file_path = file_path
        self._strategy = strategy

    def run(self) -> None:
        try:
            svc = MigrationService(
                self._file_path, stock_strategy=self._strategy)
            result = svc.dry_run()
            self.finished.emit(result)
        except Exception as e:
            self.error.emit(str(e))


class _ExecuteWorker(QThread):
    progress = Signal(int, str)
    finished = Signal(object)
    error = Signal(str)

    def __init__(
        self, source_path: str, target_db: str, strategy: str
    ) -> None:
        super().__init__()
        self._source_path = source_path
        self._target_db = target_db
        self._strategy = strategy

    def run(self) -> None:
        try:
            self.progress.emit(10, '开始迁移...')
            executor = MigrationExecutor(
                self._source_path, self._target_db,
                stock_strategy=self._strategy,
            )
            self.progress.emit(30, '执行迁移...')
            report = executor.execute(backup=True)
            self.progress.emit(90, '验证中...')
            self.finished.emit(report)
            self.progress.emit(100, '完成')
        except Exception as e:
            self.error.emit(str(e))


class ImportWizard(QWidget):
    """导入向导主控件。"""

    def __init__(self) -> None:
        super().__init__()
        self._source_path: str = ''
        self._audit_result: dict | None = None
        self._dry_run_plan: MigrationPlan | None = None
        self._strategy: str = 'historical_snapshot'
        self._target_db_path: str = ''
        self._report: dict | None = None
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        title = QLabel('数据导入向导')
        title.setStyleSheet(
            'font-size: 22px; font-weight: bold; color: #fff;')
        layout.addWidget(title)

        desc = QLabel('从旧 .mym 账套迁移数据到 MYM2 新系统')
        desc.setStyleSheet('color: #999; font-size: 13px;')
        layout.addWidget(desc)

        self._step_stack = QStackedWidget()
        self._step_stack.addWidget(self._create_step1_select())
        self._step_stack.addWidget(self._create_step2_precheck())
        self._step_stack.addWidget(self._create_step3_strategy())
        self._step_stack.addWidget(self._create_step4_plan())
        self._step_stack.addWidget(self._create_step5_confirm())
        self._step_stack.addWidget(self._create_step6_results())
        layout.addWidget(self._step_stack, stretch=1)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        self._back_btn = QPushButton('← 上一步')
        self._back_btn.setEnabled(False)
        self._back_btn.clicked.connect(self._go_back)
        btn_layout.addWidget(self._back_btn)

        self._report_only_btn = QPushButton('仅生成报告')
        self._report_only_btn.setStyleSheet(
            'QPushButton { background: #555; color: #fff; padding: 8px 20px;'
            ' border-radius: 6px; font-size: 14px; }')
        self._report_only_btn.clicked.connect(self._run_report_only)
        btn_layout.addWidget(self._report_only_btn)

        self._next_btn = QPushButton('下一步 →')
        self._next_btn.setStyleSheet(
            'QPushButton { background: #4a6cf7; color: #fff;'
            ' padding: 8px 24px; border-radius: 6px; font-size: 14px;'
            ' font-weight: bold; }'
            'QPushButton:hover { background: #5b7df8; }'
            'QPushButton:disabled { background: #333; color: #666; }')
        self._next_btn.clicked.connect(self._go_next)
        btn_layout.addWidget(self._next_btn)

        self._import_btn = QPushButton('导入到新账本')
        self._import_btn.setStyleSheet(
            'QPushButton { background: #e74c3c; color: #fff;'
            ' padding: 8px 24px; border-radius: 6px; font-size: 14px;'
            ' font-weight: bold; }'
            'QPushButton:hover { background: #f05a4c; }'
            'QPushButton:disabled { background: #333; color: #666; }')
        self._import_btn.clicked.connect(self._start_import)
        self._import_btn.setVisible(False)
        btn_layout.addWidget(self._import_btn)

        layout.addLayout(btn_layout)
        self._update_buttons()

    def _create_step1_select(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        group = QGroupBox('选择旧账套文件')
        form = QFormLayout(group)

        self._file_label = QLabel('未选择文件')
        self._file_label.setStyleSheet('color: #aaa;')
        browse_btn = QPushButton('浏览...')
        browse_btn.clicked.connect(self._browse_file)
        row = QHBoxLayout()
        row.addWidget(self._file_label, stretch=1)
        row.addWidget(browse_btn)
        form.addRow('旧 .mym 文件:', row)

        self._db_label = QLabel('使用默认新账本路径')
        self._db_label.setStyleSheet('color: #aaa;')
        db_btn = QPushButton('选择...')
        db_btn.clicked.connect(self._browse_target_db)
        row2 = QHBoxLayout()
        row2.addWidget(self._db_label, stretch=1)
        row2.addWidget(db_btn)
        form.addRow('目标账本:', row2)

        layout.addWidget(group)
        info = QLabel(
            '旧 .mym 文件将以只读方式打开，不会修改原始文件。\n'
            '请确保已将旧账套文件放置在可访问的路径。')
        info.setStyleSheet('color: #888; font-size: 12px; padding: 12px;')
        info.setWordWrap(True)
        layout.addWidget(info)
        layout.addStretch()
        return page

    def _create_step2_precheck(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        self._precheck_status = QLabel('点击"下一步"开始预检查...')
        self._precheck_status.setStyleSheet(
            'color: #aaa; font-size: 14px; padding: 12px;')
        layout.addWidget(self._precheck_status)
        self._precheck_text = QPlainTextEdit()
        self._precheck_text.setReadOnly(True)
        self._precheck_text.setStyleSheet(
            'QPlainTextEdit { background: #1a1b2e; color: #ddd;'
            ' font-family: monospace; font-size: 12px;'
            ' border: 1px solid #333; }')
        layout.addWidget(self._precheck_text)
        self._precheck_progress = QProgressBar()
        self._precheck_progress.setVisible(False)
        layout.addWidget(self._precheck_progress)
        return page

    def _create_step3_strategy(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        group = QGroupBox('股票/证券数据处理策略')
        form = QFormLayout(group)

        self._strategy_combo = QComboBox()
        self._strategy_combo.addItem(
            '历史投资快照（推荐）', 'historical_snapshot')
        self._strategy_combo.addItem(
            '仅归档', 'archive_only')
        self._strategy_combo.addItem(
            '跳过', 'skip')
        self._strategy_combo.setCurrentIndex(0)
        self._strategy_combo.currentIndexChanged.connect(
            self._on_strategy_changed)
        form.addRow('策略:', self._strategy_combo)

        self._strategy_desc = QLabel(
            '历史投资快照：链接证券→不可编辑快照账户+调节流水，'
            '股票数据归档到历史记录。'
            '调节流水不纳入日常收支/预算统计。')
        self._strategy_desc.setWordWrap(True)
        self._strategy_desc.setStyleSheet(
            'color: #aaa; font-size: 12px; padding: 8px;')
        form.addRow(self._strategy_desc)

        layout.addWidget(group)
        layout.addStretch()
        return page

    def _create_step4_plan(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        self._plan_status = QLabel('点击"下一步"生成迁移计划...')
        self._plan_status.setStyleSheet(
            'color: #aaa; font-size: 14px; padding: 8px;')
        layout.addWidget(self._plan_status)
        self._plan_text = QTextEdit()
        self._plan_text.setReadOnly(True)
        self._plan_text.setStyleSheet(
            'QTextEdit { background: #1a1b2e; color: #ddd;'
            ' font-family: monospace; font-size: 12px;'
            ' border: 1px solid #333; }')
        layout.addWidget(self._plan_text)
        return page

    def _create_step5_confirm(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        warning = QLabel('⚠️ 最终确认')
        warning.setStyleSheet(
            'font-size: 18px; font-weight: bold; color: #e74c3c;')
        layout.addWidget(warning)

        self._confirm_text = QLabel()
        self._confirm_text.setWordWrap(True)
        self._confirm_text.setStyleSheet(
            'color: #ddd; font-size: 13px; padding: 12px;')
        layout.addWidget(self._confirm_text)

        self._backup_check = QCheckBox('迁移前自动备份目标数据库')
        self._backup_check.setChecked(True)
        self._backup_check.setStyleSheet('color: #ccc;')
        layout.addWidget(self._backup_check)

        self._confirm_check = QCheckBox('我确认以上信息，开始执行迁移')
        self._confirm_check.setStyleSheet(
            'color: #ccc; font-weight: bold;')
        self._confirm_check.toggled.connect(self._update_buttons)
        layout.addWidget(self._confirm_check)

        layout.addStretch()
        return page

    def _create_step6_results(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        self._result_status = QLabel()
        self._result_status.setStyleSheet(
            'font-size: 16px; font-weight: bold; padding: 8px;')
        layout.addWidget(self._result_status)

        self._result_progress = QProgressBar()
        self._result_progress.setVisible(False)
        layout.addWidget(self._result_progress)

        self._result_text = QTextEdit()
        self._result_text.setReadOnly(True)
        self._result_text.setStyleSheet(
            'QTextEdit { background: #1a1b2e; color: #ddd;'
            ' font-family: monospace; font-size: 12px;'
            ' border: 1px solid #333; }')
        layout.addWidget(self._result_text)
        return page

    def _go_next(self) -> None:
        cur = self._step_stack.currentIndex()
        if cur == 0:
            self._validate_file_and_proceed()
        elif cur == 1:
            self._step_stack.setCurrentIndex(2)
        elif cur == 2:
            self._generate_plan()
        elif cur == 3:
            self._step_stack.setCurrentIndex(4)
        self._update_buttons()

    def _go_back(self) -> None:
        cur = self._step_stack.currentIndex()
        if cur > 0:
            self._step_stack.setCurrentIndex(cur - 1)
        self._update_buttons()

    def _update_buttons(self) -> None:
        cur = self._step_stack.currentIndex()
        self._back_btn.setEnabled(cur > 0)
        self._next_btn.setVisible(cur < 4)
        self._report_only_btn.setVisible(cur in (0, 1, 2, 3))
        self._import_btn.setVisible(cur == 4)
        self._import_btn.setEnabled(
            cur == 4 and self._confirm_check.isChecked())
        if cur >= 4:
            self._next_btn.setEnabled(False)

    def _browse_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, '选择旧 .mym 文件', '',
            'MYM 文件 (*.mym);;SQLite 文件 (*.db);;所有文件 (*)')
        if path:
            self._source_path = path
            self._file_label.setText(path)
            self._file_label.setStyleSheet('color: #4a6cf7;')
            self._update_buttons()

    def _browse_target_db(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, '选择目标账本位置', 'mym2_data.db', 'SQLite 文件 (*.db)')
        if path:
            self._target_db_path = path
            self._db_label.setText(path)
            self._db_label.setStyleSheet('color: #4a6cf7;')

    def _validate_file_and_proceed(self) -> None:
        if not self._source_path:
            QMessageBox.warning(self, '提示', '请先选择旧 .mym 文件')
            return
        self._precheck_status.setText('正在执行只读预检查...')
        self._precheck_progress.setVisible(True)
        self._precheck_progress.setRange(0, 0)
        self._audit_worker = _AuditWorker(self._source_path)
        self._audit_worker.finished.connect(self._on_audit_done)
        self._audit_worker.error.connect(self._on_audit_error)
        self._audit_worker.start()

    def _on_audit_done(self, result: dict) -> None:
        self._audit_result = result
        self._precheck_progress.setVisible(False)
        summary = result.get('summary', {})
        integrity = result.get('integrity', {})
        meta = result['meta']
        lines = [
            '✅ 预检查完成\n',
            f'📁 文件: {meta["source_path"]}',
            f'🔒 未修改: {"✅" if meta["hash_unchanged"] else "❌"}',
            f'📊 表: {summary.get("table_count", 0)}',
            f'📝 总行: {summary.get("total_rows", 0)}',
            f'🔍 完整性: {"✅" if integrity.get("integrity_ok") else "❌"}',
            f'💹 链接证券: '
            f'{len(summary.get("linked_stock_accounts", []))} 个',
        ]
        self._precheck_text.setPlainText('\n'.join(lines))
        self._precheck_status.setText('预检查完成')
        self._precheck_status.setStyleSheet(
            'color: #27ae60; font-size: 14px; padding: 12px;')
        self._step_stack.setCurrentIndex(1)
        self._update_buttons()

    def _on_audit_error(self, error: str) -> None:
        self._precheck_progress.setVisible(False)
        self._precheck_status.setText(f'预检查失败: {error}')
        self._precheck_status.setStyleSheet(
            'color: #e74c3c; font-size: 14px; padding: 12px;')

    def _on_strategy_changed(self, index: int) -> None:
        self._strategy = self._strategy_combo.currentData()
        descs = {
            'historical_snapshot':
                '历史投资快照：链接证券→不可编辑快照账户+调节流水。',
            'archive_only': '仅归档：股票数据归档，不创建新账户。',
            'skip': '跳过：不处理任何股票数据。',
        }
        self._strategy_desc.setText(descs.get(self._strategy, ''))

    def _generate_plan(self) -> None:
        self._plan_status.setText('正在生成迁移计划（dry-run）...')
        self._plan_status.setStyleSheet(
            'color: #f39c12; font-size: 14px; padding: 8px;')
        self._plan_worker = _PlanWorker(
            self._source_path, self._strategy)
        self._plan_worker.finished.connect(self._on_plan_done)
        self._plan_worker.error.connect(self._on_plan_error)
        self._plan_worker.start()

    def _on_plan_done(self, result) -> None:
        self._dry_run_plan = result.plan
        plan = result.plan
        lines = ['📋 迁移计划（dry-run）\n']
        lines.append('## 表迁移计划')
        hdr = f'| {"表名":<20} | {"总数":>6} | {"迁移":>6} | {"归档":>6} |'
        lines.append(hdr)
        lines.append(f'|{"-"*20}-|{"-"*6}-|{"-"*6}-|{"-"*6}|')
        for tp in plan.table_plans:
            lines.append(
                f'| {tp.table_name:<20} | {tp.total_rows:>6} |'
                f' {tp.rows_to_migrate:>6} | {tp.rows_to_archive:>6} |')
        lines.append(f'\n📊 预估: {plan.estimated_new_records} 条')
        if plan.risks:
            lines.append(f'\n## 🚨 风险 ({len(plan.risks)} 项)')
            for risk in plan.risks:
                lines.append(f'  [{risk.severity.upper()}] {risk.description}')
        self._plan_text.setMarkdown('\n'.join(lines))
        self._plan_status.setText('计划生成完成')
        self._plan_status.setStyleSheet(
            'color: #27ae60; font-size: 14px; padding: 8px;')
        self._step_stack.setCurrentIndex(3)
        self._update_buttons()

    def _on_plan_error(self, error: str) -> None:
        self._plan_status.setText(f'计划生成失败: {error}')
        self._plan_status.setStyleSheet(
            'color: #e74c3c; font-size: 14px; padding: 8px;')

    def _run_report_only(self) -> None:
        if not self._source_path:
            QMessageBox.warning(self, '提示', '请先选择旧 .mym 文件')
            return
        save_path, _ = QFileDialog.getSaveFileName(
            self, '保存报告', 'migration_report.json', 'JSON (*.json)')
        if not save_path:
            return
        try:
            svc = MigrationService(
                self._source_path, stock_strategy=self._strategy)
            svc.dry_run_to_file(save_path)
            QMessageBox.information(self, '完成', f'报告已保存到:\n{save_path}')
        except Exception as e:
            QMessageBox.critical(self, '错误', f'生成报告失败:\n{e}')

    def _start_import(self) -> None:
        if not self._target_db_path:
            self._target_db_path = str(
                Path(self._source_path).parent / 'mym2_data.db')
        reply = QMessageBox.question(
            self, '确认导入',
            f'即将从旧账套迁移数据到:\n{self._target_db_path}\n\n'
            f'策略: {self._strategy}\n'
            f'迁移前将自动备份目标数据库。\n\n是否确认开始？',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._step_stack.setCurrentIndex(5)
        self._result_status.setText('正在执行迁移...')
        self._result_status.setStyleSheet(
            'color: #f39c12; font-size: 16px;')
        self._result_progress.setVisible(True)
        self._result_progress.setRange(0, 100)
        self._exec_worker = _ExecuteWorker(
            self._source_path, self._target_db_path, self._strategy)
        self._exec_worker.progress.connect(self._on_exec_progress)
        self._exec_worker.finished.connect(self._on_exec_done)
        self._exec_worker.error.connect(self._on_exec_error)
        self._exec_worker.start()

    def _on_exec_progress(self, value: int, msg: str) -> None:
        self._result_progress.setValue(value)
        self._result_status.setText(msg)

    def _on_exec_done(self, report: dict) -> None:
        self._report = report
        self._result_progress.setVisible(False)
        stats = report.get('stats', {})
        ver = report.get('verification', {})
        lines = [
            '# ✅ 迁移完成\n',
            f'**状态**: {report["status"]}',
            f'**策略**: {report["stock_strategy"]}',
            f'**备份**: {report.get("backup_path", "无")}',
            '',
            '## 导入统计',
            f'| 账户 | {stats.get("accounts_imported", 0)} |',
            f'| 分类 | {stats.get("categories_imported", 0)} |',
            f'| 流水 | {stats.get("transactions_imported", 0)} |',
            f'| 预算 | {stats.get("budget_periods_imported", 0)} |',
            f'| 预算行 | {stats.get("budget_lines_imported", 0)} |',
            f'| 设置 | {stats.get("settings_imported", 0)} |',
            f'| 归档 | {stats.get("archived", 0)} |',
            f'| 跳过 | {stats.get("skipped", 0)} |',
            f'| 失败 | {stats.get("failed", 0)} |',
            '',
            '## 验证',
            f'- FK: {"✅" if ver.get("fk_ok") else "❌"}',
            f'- 完整性: {"✅" if ver.get("integrity_ok") else "❌"}',
        ]
        if ver.get('errors'):
            lines.append('\n### 错误')
            for e in ver['errors']:
                lines.append(f'- ❌ {e}')
        self._result_text.setMarkdown('\n'.join(lines))
        self._result_status.setText('迁移完成')
        self._result_status.setStyleSheet(
            'color: #27ae60; font-size: 16px;')
        self._import_btn.setVisible(False)
        self._update_buttons()

    def _on_exec_error(self, error: str) -> None:
        self._result_progress.setVisible(False)
        self._result_status.setText('迁移失败')
        self._result_status.setStyleSheet(
            'color: #e74c3c; font-size: 16px;')
        self._result_text.setMarkdown(
            f'# ❌ 迁移失败\n\n'
            f'**错误**: {error}\n\n'
            f'事务已回滚，目标数据库未受影响。\n'
            f'请检查旧账套文件后重试。')
        self._update_buttons()
