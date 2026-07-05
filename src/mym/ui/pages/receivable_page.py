"""ReceivablePage – accounts receivable management (advance, recover, write-off, import)."""

import logging
from decimal import Decimal

from PySide6.QtCore import QDate, QObject, QThread, Qt, Signal, Slot
from PySide6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableView,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from mym.application.services.export_service import ExportService
from mym.application.services.receivable_service import ReceivableService
from mym.ui.navigation import AppEventBus
from mym.ui.widgets.table_model import BaseTableModel, ColumnDef

logger = logging.getLogger(__name__)


class _AdvanceDialog(QDialog):
    """Dialog for creating a new advance/lend."""

    def __init__(self, accounts: list[dict], parent=None):
        super().__init__(parent)
        self.setWindowTitle("新增应收 / 垫付")
        self.resize(400, 300)

        layout = QFormLayout(self)

        self._account_combo = QComboBox()
        for acc in accounts:
            self._account_combo.addItem(acc["name"], acc["id"])
        layout.addRow("应收账户:", self._account_combo)

        self._debtor_edit = QLineEdit()
        layout.addRow("债务人:", self._debtor_edit)

        self._amount_edit = QLineEdit("0.00")
        layout.addRow("金额:", self._amount_edit)

        self._date_edit = QDateEdit(QDate.currentDate())
        self._date_edit.setCalendarPopup(True)
        layout.addRow("日期:", self._date_edit)

        self._notes_edit = QLineEdit()
        layout.addRow("备注:", self._notes_edit)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def get_data(self) -> dict:
        return {
            "account_id": self._account_combo.currentData(),
            "debtor": self._debtor_edit.text().strip(),
            "amount": Decimal(self._amount_edit.text() or "0"),
            "date": self._date_edit.date().toPython(),
            "notes": self._notes_edit.text().strip() or None,
        }


class _RecoverDialog(QDialog):
    """Dialog for recording a recovery (partial or full)."""

    def __init__(self, case: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"收回欠款 – {case['debtor']}")
        self.resize(400, 250)

        layout = QFormLayout(self)

        layout.addRow("债务人:", QLabel(case["debtor"]))
        layout.addRow("未收余额:", QLabel(f"¥{Decimal(case['outstanding']):,.2f}"))

        self._amount_edit = QLineEdit(case["outstanding"])
        layout.addRow("收回金额:", self._amount_edit)

        self._date_edit = QDateEdit(QDate.currentDate())
        self._date_edit.setCalendarPopup(True)
        layout.addRow("日期:", self._date_edit)

        self._notes_edit = QLineEdit()
        layout.addRow("备注:", self._notes_edit)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def get_data(self) -> dict:
        return {
            "amount": Decimal(self._amount_edit.text() or "0"),
            "date": self._date_edit.date().toPython(),
            "notes": self._notes_edit.text().strip() or None,
        }


class _Worker(QObject):
    """Background worker for receivable queries."""
    finished = Signal(list, list)  # (unrecovered, all_cases)
    error = Signal(str)

    def __init__(self, session_factory, parent=None):
        super().__init__(parent)
        self._session_factory = session_factory

    @Slot()
    def run(self) -> None:
        session = self._session_factory()
        try:
            svc = ReceivableService(session)
            report = svc.get_unrecovered_report()
            self.finished.emit(report, report)
        except Exception as e:
            self.error.emit(str(e))
        finally:
            session.close()


class ReceivablePage(QWidget):
    """Accounts receivable management page."""

    def __init__(self, session_factory=None, parent=None):
        super().__init__(parent)
        self._session_factory = session_factory
        self._cases: list[dict] = []
        self._worker: QThread | None = None
        self._setup_ui()

    def _setup_ui(self) -> None:
        main_layout = QVBoxLayout(self)

        # ── Toolbar ──
        toolbar = QHBoxLayout()
        self._add_btn = QPushButton("新增应收")
        self._add_btn.clicked.connect(self._on_add_advance)
        toolbar.addWidget(self._add_btn)

        self._recover_btn = QPushButton("收回欠款")
        self._recover_btn.clicked.connect(self._on_recover)
        toolbar.addWidget(self._recover_btn)

        self._writeoff_btn = QPushButton("核销")
        self._writeoff_btn.clicked.connect(self._on_write_off)
        toolbar.addWidget(self._writeoff_btn)

        self._import_btn = QPushButton("导入CSV")
        self._import_btn.clicked.connect(self._on_import_csv)
        toolbar.addWidget(self._import_btn)

        self._export_btn = QPushButton("导出")
        self._export_btn.clicked.connect(self._on_export)
        toolbar.addWidget(self._export_btn)

        toolbar.addStretch()
        main_layout.addLayout(toolbar)

        # ── Summary ──
        summary_frame = QFrame()
        summary_frame.setFrameStyle(QFrame.Shape.StyledPanel)
        slayout = QHBoxLayout(summary_frame)
        self._total_lbl = QLabel("应收总计: —")
        self._total_lbl.setStyleSheet("font-size: 14px; font-weight: bold; color: #1976D2;")
        self._count_lbl = QLabel("共 0 条")
        slayout.addWidget(self._total_lbl)
        slayout.addStretch()
        slayout.addWidget(self._count_lbl)
        main_layout.addWidget(summary_frame)

        # ── Table ──
        columns = [
            ColumnDef("debtor", "债务人", 120),
            ColumnDef("total", "总额", 100, Qt.AlignmentFlag.AlignRight),
            ColumnDef("recovered", "已收回", 100, Qt.AlignmentFlag.AlignRight),
            ColumnDef("outstanding", "未收", 100, Qt.AlignmentFlag.AlignRight),
            ColumnDef("status", "状态", 100),
            ColumnDef("occurrence_date", "日期", 100),
            ColumnDef("notes", "备注", 200),
        ]
        self._model = BaseTableModel(columns)
        self._table = QTableView()
        self._table.setModel(self._model)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QTableView.SelectionMode.SingleSelection)
        main_layout.addWidget(self._table)

    def _run_query(self) -> None:
        if self._worker and getattr(self._worker, 'isRunning', lambda: False)():
            return
        self._add_btn.setEnabled(False)

        self._thread = QThread()
        self._worker_obj = _Worker(self._session_factory)
        self._worker_obj.moveToThread(self._thread)
        self._thread.started.connect(self._worker_obj.run)
        self._worker_obj.finished.connect(self._on_data_loaded)
        self._worker_obj.error.connect(self._on_error)
        self._worker_obj.finished.connect(self._thread.quit)
        self._worker_obj.finished.connect(self._worker_obj.deleteLater)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.start()

    @Slot(list, list)
    def _on_data_loaded(self, unrecovered: list[dict], all_cases: list[dict]) -> None:
        self._cases = all_cases
        self._add_btn.setEnabled(True)

        status_labels = {
            "pending": "待收", "partially_recovered": "部分收回",
            "fully_recovered": "已收回", "written_off": "已核销",
        }
        total = Decimal("0")
        rows = []
        for c in all_cases:
            total += Decimal(c["outstanding"])
            rows.append({
                "debtor": c["debtor"],
                "total": f"¥{Decimal(c['total']):,.2f}",
                "recovered": f"¥{Decimal(c['recovered']):,.2f}",
                "outstanding": f"¥{Decimal(c['outstanding']):,.2f}",
                "status": status_labels.get(c["status"], c["status"]),
                "occurrence_date": c["occurrence_date"],
                "notes": c["notes"],
            })
        self._model.set_data(rows)
        self._total_lbl.setText(f"未收总计: ¥{total:,.2f}")
        self._count_lbl.setText(f"共 {len(all_cases)} 条")

    @Slot(str)
    def _on_error(self, msg: str) -> None:
        self._add_btn.setEnabled(True)
        QMessageBox.critical(self, "错误", f"查询失败: {msg}")

    def _get_selected_case(self) -> dict | None:
        """Get the currently selected case data."""
        idx = self._table.currentIndex()
        if not idx.isValid():
            return None
        row = idx.row()
        if row >= len(self._cases):
            return None
        return self._cases[row]

    def _on_add_advance(self) -> None:
        """Open dialog to create a new advance."""
        # Get receivable accounts
        session = self._session_factory()
        try:
            from mym.infrastructure.repositories.account_repo import AccountRepository
            from mym.domain.enums import AccountType
            repo = AccountRepository(session)
            accounts = repo.list_by_type(AccountType.RECEIVABLE)
            if not accounts:
                QMessageBox.warning(self, "提示", "没有可用的应收账户，请先在账户管理中创建应收类型账户")
                return

            acc_list = [{"id": a.id, "name": a.name} for a in accounts]

            dlg = _AdvanceDialog(acc_list, self)
            if dlg.exec() != QDialog.DialogCode.Accepted:
                return

            data = dlg.get_data()
            if data["amount"] <= 0:
                QMessageBox.warning(self, "错误", "金额必须大于0")
                return
            if not data["debtor"]:
                QMessageBox.warning(self, "错误", "请输入债务人")
                return

            svc = ReceivableService(session)
            result = svc.create_advance(
                account_id=data["account_id"],
                debtor=data["debtor"],
                amount=data["amount"],
                occurrence_date=data["date"],
                notes=data["notes"],
            )
            session.commit()

            if result.success:
                AppEventBus.instance().ledger_changed.emit()
                self._run_query()
                QMessageBox.information(self, "成功", f"应收记录已创建 (ID: {result.case_id})")
            else:
                QMessageBox.critical(self, "错误", "\n".join(result.errors))
        except Exception as e:
            session.rollback()
            QMessageBox.critical(self, "错误", str(e))
        finally:
            session.close()

    def _on_recover(self) -> None:
        """Record a recovery."""
        case = self._get_selected_case()
        if not case:
            QMessageBox.warning(self, "提示", "请先选择一条应收记录")
            return
        if case["status"] in ("fully_recovered", "written_off"):
            QMessageBox.warning(self, "提示", "该记录已完成，无法再收回")
            return

        dlg = _RecoverDialog(case, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        data = dlg.get_data()
        if data["amount"] <= 0:
            QMessageBox.warning(self, "错误", "金额必须大于0")
            return

        session = self._session_factory()
        try:
            svc = ReceivableService(session)
            result = svc.recover(
                case_id=case["id"],
                amount=data["amount"],
                event_date=data["date"],
                notes=data["notes"],
            )
            session.commit()
            if result.success:
                AppEventBus.instance().ledger_changed.emit()
                self._run_query()
                QMessageBox.information(self, "成功", "收回欠款已记录")
            else:
                QMessageBox.critical(self, "错误", "\n".join(result.errors))
        except Exception as e:
            session.rollback()
            QMessageBox.critical(self, "错误", str(e))
        finally:
            session.close()

    def _on_write_off(self) -> None:
        """Write off a receivable as bad debt."""
        case = self._get_selected_case()
        if not case:
            QMessageBox.warning(self, "提示", "请先选择一条应收记录")
            return
        if case["status"] in ("fully_recovered", "written_off"):
            QMessageBox.warning(self, "提示", "该记录已完成，无法再核销")
            return

        session = self._session_factory()
        try:
            svc = ReceivableService(session)
            outstanding = Decimal(case["outstanding"])
            result = svc.write_off(
                case_id=case["id"],
                amount=outstanding,
                event_date=QDate.currentDate().toPython(),
                notes="坏账核销",
            )
            session.commit()
            if result.success:
                AppEventBus.instance().ledger_changed.emit()
                self._run_query()
                QMessageBox.information(self, "成功", "核销完成")
            else:
                QMessageBox.critical(self, "错误", "\n".join(result.errors))
        except Exception as e:
            session.rollback()
            QMessageBox.critical(self, "错误", str(e))
        finally:
            session.close()

    def _on_import_csv(self) -> None:
        """Import receivable data from CSV."""
        path, _ = QFileDialog.getOpenFileName(
            self, "导入应收期初CSV", "", "CSV文件 (*.csv)"
        )
        if not path:
            return

        import csv
        session = self._session_factory()
        try:
            from mym.infrastructure.repositories.account_repo import AccountRepository
            from mym.domain.enums import AccountType
            repo = AccountRepository(session)
            accounts = repo.list_by_type(AccountType.RECEIVABLE)
            if not accounts:
                QMessageBox.warning(self, "提示", "没有可用的应收账户")
                return
            acc = accounts[0]

            svc = ReceivableService(session)
            success_count = 0
            errors = []

            with open(path, encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                for row_num, row in enumerate(reader, 2):
                    try:
                        debtor = row.get("债务人", row.get("debtor", "")).strip()
                        amount = Decimal(row.get("待收增加", row.get("amount", "0")))
                        date_str = row.get("日期", row.get("date", ""))
                        notes = row.get("备注", row.get("notes", ""))

                        from datetime import date as dt_date
                        try:
                            d = dt_date.fromisoformat(date_str)
                        except (ValueError, TypeError):
                            d = dt_date.today()

                        if not debtor or amount <= 0:
                            errors.append(f"第{row_num}行: 债务人或金额无效")
                            continue

                        result = svc.create_advance(
                            account_id=acc.id,
                            debtor=debtor,
                            amount=amount,
                            occurrence_date=d,
                            notes=notes or "期初导入",
                        )
                        if result.success:
                            success_count += 1
                        else:
                            errors.append(f"第{row_num}行: {result.errors}")
                    except Exception as e:
                        errors.append(f"第{row_num}行: {e}")

            session.commit()

            msg = f"成功导入 {success_count} 条记录"
            if errors:
                msg += f"\n\n错误 ({len(errors)} 条):\n" + "\n".join(errors[:5])
            QMessageBox.information(self, "导入结果", msg)

            AppEventBus.instance().ledger_changed.emit()
            self._run_query()
        except Exception as e:
            session.rollback()
            QMessageBox.critical(self, "导入失败", str(e))
        finally:
            session.close()

    def _on_export(self) -> None:
        """Export receivable data to CSV."""
        if not self._cases:
            QMessageBox.information(self, "提示", "没有数据可导出")
            return

        headers = ["debtor", "total", "recovered", "outstanding", "status", "occurrence_date", "notes"]
        rows = []
        for c in self._cases:
            rows.append({
                "debtor": c["debtor"],
                "total": c["total"],
                "recovered": c["recovered"],
                "outstanding": c["outstanding"],
                "status": c["status"],
                "occurrence_date": c["occurrence_date"],
                "notes": c["notes"],
            })

        ok, path, msg = ExportService.export_csv(rows, headers, prefix="receivable")
        QMessageBox.information(self, "导出结果", msg)

    def on_enter(self) -> None:
        self._run_query()

    def on_leave(self) -> None:
        pass
