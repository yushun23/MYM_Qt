"""StockPage – investment module UI with holdings, trades, settlement."""

import logging
from datetime import date
from decimal import Decimal

from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTabWidget,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from mym.application.services.stock_trading_service import StockTradingService
from mym.application.services.settlement_service import SettlementService
from mym.application.services.investment_service import InvestmentService
from mym.application.services.quote_service import QuoteService
from mym.domain.entities.investment import InvestmentAccount
from mym.domain.enums import InvestmentModuleStatus
from mym.ui.navigation import AppEventBus
from mym.ui.widgets.table_model import BaseTableModel, ColumnDef

logger = logging.getLogger(__name__)


class StockPage(QWidget):
    """Investment module main page."""

    def __init__(self, session_factory=None, parent=None):
        super().__init__(parent)
        self._session_factory = session_factory
        self._setup_ui()

        AppEventBus.instance().investment_changed.connect(self.refresh)
        AppEventBus.instance().module_visibility_changed.connect(self.refresh)

    def _session(self):
        if self._session_factory:
            return self._session_factory()
        return None

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)

        tabs = QTabWidget()
        tabs.addTab(self._build_holdings_tab(), "持仓")
        tabs.addTab(self._build_trading_tab(), "交易")
        tabs.addTab(self._build_settlement_tab(), "月结")
        tabs.addTab(self._build_management_tab(), "管理")

        layout.addWidget(tabs)

    # --- Holdings Tab ---

    def _build_holdings_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)

        # Summary
        self._holdings_summary = QLabel("总资产: — | 总市值: — | 现金: —")
        self._holdings_summary.setStyleSheet("font-size: 14px; font-weight: bold;")
        layout.addWidget(self._holdings_summary)

        # Holdings table
        cols = [
            ColumnDef("symbol", "代码", 80),
            ColumnDef("name", "名称", 120),
            ColumnDef("quantity", "数量", 80, Qt.AlignmentFlag.AlignRight),
            ColumnDef("avg_cost", "成本价", 80, Qt.AlignmentFlag.AlignRight),
            ColumnDef("market_price", "市价", 80, Qt.AlignmentFlag.AlignRight),
            ColumnDef("market_value", "市值", 100, Qt.AlignmentFlag.AlignRight),
            ColumnDef("unrealized_pnl", "浮动盈亏", 100, Qt.AlignmentFlag.AlignRight),
            ColumnDef("pnl_pct", "盈亏%", 70, Qt.AlignmentFlag.AlignRight),
        ]
        self._holdings_model = BaseTableModel(cols)
        self._holdings_table = QTableView()
        self._holdings_table.setModel(self._holdings_model)
        self._holdings_table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self._holdings_table)

        return w

    # --- Trading Tab ---

    def _build_trading_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)

        # Quick actions
        actions = QHBoxLayout()
        for label, slot in [
            ("买入", self._on_buy),
            ("卖出", self._on_sell),
            ("股息", self._on_dividend),
            ("银证转账", self._on_transfer),
        ]:
            btn = QPushButton(label)
            btn.clicked.connect(slot)
            actions.addWidget(btn)
        actions.addStretch()
        layout.addLayout(actions)

        # Recent trades
        cols = [
            ColumnDef("date", "日期", 100),
            ColumnDef("symbol", "代码", 70),
            ColumnDef("type", "类型", 50),
            ColumnDef("quantity", "数量", 80, Qt.AlignmentFlag.AlignRight),
            ColumnDef("price", "价格", 80, Qt.AlignmentFlag.AlignRight),
            ColumnDef("amount", "金额", 100, Qt.AlignmentFlag.AlignRight),
            ColumnDef("fee", "费用", 80, Qt.AlignmentFlag.AlignRight),
        ]
        self._trades_model = BaseTableModel(cols)
        self._trades_table = QTableView()
        self._trades_table.setModel(self._trades_model)
        self._trades_table.horizontalHeader().setStretchLastSection(True)
        self._trades_table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        layout.addWidget(self._trades_table)

        btns = QHBoxLayout()
        edit_btn = QPushButton("编辑选中")
        edit_btn.clicked.connect(self._on_edit_trade)
        delete_btn = QPushButton("删除选中")
        delete_btn.clicked.connect(self._on_delete_trade)
        delete_btn.setStyleSheet("QPushButton { background-color: #D32F2F; }")
        btns.addWidget(edit_btn)
        btns.addWidget(delete_btn)
        btns.addStretch()
        layout.addLayout(btns)

        return w

    # --- Settlement Tab ---

    def _build_settlement_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)

        # Settlement controls
        controls = QHBoxLayout()
        controls.addWidget(QLabel("年份:"))
        self._settle_year = QSpinBox()
        self._settle_year.setRange(2000, 2100)
        self._settle_year.setValue(date.today().year)
        controls.addWidget(self._settle_year)

        controls.addWidget(QLabel("月份:"))
        self._settle_month = QSpinBox()
        self._settle_month.setRange(1, 12)
        self._settle_month.setValue(date.today().month)
        controls.addWidget(self._settle_month)

        preview_btn = QPushButton("预览")
        preview_btn.clicked.connect(self._on_preview_settlement)
        controls.addWidget(preview_btn)

        generate_btn = QPushButton("生成月结")
        generate_btn.clicked.connect(self._on_generate_settlement)
        controls.addWidget(generate_btn)

        void_btn = QPushButton("作废")
        void_btn.clicked.connect(self._on_void_settlement)
        controls.addWidget(void_btn)
        controls.addStretch()
        layout.addLayout(controls)

        # Settlement list
        cols = [
            ColumnDef("period", "月份", 100),
            ColumnDef("net_inflow", "净流入", 100, Qt.AlignmentFlag.AlignRight),
            ColumnDef("realized_pnl", "已实现盈亏", 100, Qt.AlignmentFlag.AlignRight),
            ColumnDef("dividend", "股息", 100, Qt.AlignmentFlag.AlignRight),
            ColumnDef("fees", "费用", 80, Qt.AlignmentFlag.AlignRight),
            ColumnDef("active", "状态", 60),
        ]
        self._settlement_model = BaseTableModel(cols)
        self._settlement_table = QTableView()
        self._settlement_table.setModel(self._settlement_model)
        self._settlement_table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self._settlement_table)

        return w

    # --- Management Tab ---

    def _build_management_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)

        info = QLabel(
            "投资模块管理：\n"
            "• 隐藏：从界面中移除，数据保留\n"
            "• 归档：不参与默认统计，数据保留\n"
            "• 永久删除：需先导出备份并确认"
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        self._acct_combo = QComboBox()
        layout.addWidget(self._acct_combo)

        btns = QHBoxLayout()
        for label, slot in [
            ("隐藏账户", self._on_hide_account),
            ("显示账户", self._on_show_account),
            ("归档账户", self._on_archive_account),
        ]:
            btn = QPushButton(label)
            btn.clicked.connect(slot)
            btns.addWidget(btn)
        layout.addLayout(btns)

        layout.addStretch()
        return w

    # --- Refresh ---

    def on_enter(self) -> None:
        self.refresh()

    def on_leave(self) -> None:
        pass

    def refresh(self) -> None:
        self._load_holdings()
        self._load_trades()
        self._load_settlements()
        self._load_accounts()

    def _get_active_account_id(self) -> int | None:
        session = self._session()
        if not session:
            return None
        try:
            from mym.infrastructure.repositories.investment_repo import InvestmentRepository
            repo = InvestmentRepository(session)
            visible = repo.list_visible_accounts()
            return visible[0].id if visible else None
        finally:
            session.close()

    def _load_holdings(self) -> None:
        session = self._session()
        if not session:
            return
        try:
            from mym.infrastructure.repositories.investment_repo import InvestmentRepository
            repo = InvestmentRepository(session)
            svc = StockTradingService(session)
            visible = repo.list_visible_accounts()
            if not visible:
                return

            acct_id = visible[0].id
            holdings = svc.get_holdings(acct_id)
            total_value = svc.get_total_asset_value(acct_id)
            market_value = sum(h.market_value for h in holdings)
            cash = total_value - market_value

            self._holdings_summary.setText(
                f"总资产: ¥{total_value:,.2f} | 总市值: ¥{market_value:,.2f} | 现金: ¥{cash:,.2f}"
            )

            data = []
            for h in holdings:
                data.append({
                    "symbol": h.symbol,
                    "name": h.name,
                    "quantity": str(h.quantity),
                    "avg_cost": f"¥{h.avg_cost:,.2f}",
                    "market_price": f"¥{h.market_price:,.2f}",
                    "market_value": f"¥{h.market_value:,.2f}",
                    "unrealized_pnl": f"¥{h.unrealized_pnl:,.2f}",
                    "pnl_pct": f"{h.pnl_pct}%",
                })
            self._holdings_model.set_data(data)
        finally:
            session.close()

    def _load_trades(self) -> None:
        session = self._session()
        if not session:
            return
        try:
            from mym.infrastructure.repositories.investment_repo import InvestmentRepository
            repo = InvestmentRepository(session)
            visible = repo.list_visible_accounts()
            if not visible:
                return

            trades = repo.list_trades(account_id=visible[0].id)
            data = []
            for t in trades:
                sec = repo.get_security(t.security_id)
                data.append({
                    "date": str(t.trade_date),
                    "symbol": sec.symbol if sec else "?",
                    "type": "买入" if t.trade_type == "buy" else "卖出",
                    "quantity": str(t.quantity),
                    "price": f"¥{t.price:,.2f}",
                    "amount": f"¥{t.net_amount:,.2f}",
                    "fee": f"¥{t.fee:,.2f}",
                    "_id": t.id,
                })
            self._trades_model.set_data(data)
        finally:
            session.close()

    def _load_settlements(self) -> None:
        session = self._session()
        if not session:
            return
        try:
            from mym.infrastructure.repositories.investment_repo import InvestmentRepository
            repo = InvestmentRepository(session)
            visible = repo.list_visible_accounts()
            if not visible:
                return

            settlements = repo.list_settlements(account_id=visible[0].id)
            data = []
            for s in settlements:
                if not s:
                    break
                data.append({
                    "period": s.period_label,
                    "net_inflow": f"¥{s.net_inflow:,.2f}",
                    "realized_pnl": f"¥{s.realized_pnl:,.2f}",
                    "dividend": f"¥{s.dividend_income:,.2f}",
                    "fees": f"¥{s.total_fees:,.2f}",
                    "active": "有效" if s.is_active else "已作废",
                    "_id": s.id,
                })
            self._settlement_model.set_data(data)
        finally:
            session.close()

    def _load_accounts(self) -> None:
        session = self._session()
        if not session:
            return
        try:
            from mym.infrastructure.repositories.investment_repo import InvestmentRepository
            repo = InvestmentRepository(session)
            accounts = repo.list_with_status()
            self._acct_combo.clear()
            for acct in accounts:
                label = f"{acct.name} ({acct.module_status})"
                self._acct_combo.addItem(label, acct.id)
        finally:
            session.close()

    # --- Actions ---

    def _on_buy(self) -> None:
        self._trade_dialog("buy")

    def _on_sell(self) -> None:
        self._trade_dialog("sell")

    def _trade_dialog(self, trade_type: str) -> None:
        acct_id = self._get_active_account_id()
        if not acct_id:
            QMessageBox.warning(self, "错误", "没有可用的投资账户")
            return

        dlg = QDialog(self)
        dlg.setWindowTitle("买入" if trade_type == "buy" else "卖出")
        fl = QFormLayout(dlg)

        sym_edit = QLineEdit()
        fl.addRow("证券代码:", sym_edit)

        qty_spin = QDoubleSpinBox()
        qty_spin.setDecimals(2)
        qty_spin.setRange(0, 999999999)
        fl.addRow("数量:", qty_spin)

        price_spin = QDoubleSpinBox()
        price_spin.setDecimals(4)
        price_spin.setRange(0, 999999999)
        fl.addRow("价格:", price_spin)

        fee_spin = QDoubleSpinBox()
        fee_spin.setDecimals(2)
        fee_spin.setValue(0)
        fl.addRow("费用:", fee_spin)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        fl.addRow(btns)

        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        session = self._session()
        if not session:
            return
        try:
            inv_svc = InvestmentService(session)
            svc = StockTradingService(session)
            symbol = sym_edit.text().strip()
            if not symbol:
                QMessageBox.warning(self, "错误", "请输入证券代码")
                return

            sec = inv_svc.ensure_security(symbol, symbol)
            session.flush()

            qty = Decimal(str(qty_spin.value()))
            price = Decimal(str(price_spin.value()))
            fee = Decimal(str(fee_spin.value()))

            if trade_type == "buy":
                result = svc.buy(acct_id, sec.id, date.today(), qty, price, fee=fee)
            else:
                result = svc.sell(acct_id, sec.id, date.today(), qty, price, fee=fee)

            if result.success:
                session.commit()
                AppEventBus.instance().investment_changed.emit()
                self.refresh()
            else:
                QMessageBox.warning(self, "错误", "\n".join(result.errors))
        finally:
            session.close()

    def _on_dividend(self) -> None:
        acct_id = self._get_active_account_id()
        if not acct_id:
            return

        dlg = QDialog(self)
        dlg.setWindowTitle("记录股息")
        fl = QFormLayout(dlg)

        sym_edit = QLineEdit()
        fl.addRow("证券代码:", sym_edit)

        amt_spin = QDoubleSpinBox()
        amt_spin.setDecimals(2)
        amt_spin.setRange(0, 999999999)
        fl.addRow("金额:", amt_spin)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        fl.addRow(btns)

        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        session = self._session()
        if not session:
            return
        try:
            inv_svc = InvestmentService(session)
            svc = StockTradingService(session)
            sec = inv_svc.ensure_security(sym_edit.text().strip(), sym_edit.text().strip())
            session.flush()

            result = svc.record_dividend(
                acct_id, sec.id, date.today(),
                Decimal(str(amt_spin.value())),
            )
            if result.success:
                session.commit()
                AppEventBus.instance().investment_changed.emit()
                self.refresh()
            else:
                QMessageBox.warning(self, "错误", "\n".join(result.errors))
        finally:
            session.close()

    def _on_transfer(self) -> None:
        acct_id = self._get_active_account_id()
        if not acct_id:
            return

        dlg = QDialog(self)
        dlg.setWindowTitle("银证转账")
        fl = QFormLayout(dlg)

        type_combo = QComboBox()
        type_combo.addItem("银证转入", "transfer_in")
        type_combo.addItem("银证转出", "transfer_out")
        fl.addRow("类型:", type_combo)

        amt_spin = QDoubleSpinBox()
        amt_spin.setDecimals(2)
        amt_spin.setRange(0, 999999999)
        fl.addRow("金额:", amt_spin)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        fl.addRow(btns)

        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        session = self._session()
        if not session:
            return
        try:
            from mym.domain.enums import CashFlowType
            svc = StockTradingService(session)
            ft = CashFlowType(type_combo.currentData())

            result = svc.transfer(
                acct_id, date.today(),
                Decimal(str(amt_spin.value())), ft,
            )
            if result.success:
                session.commit()
                AppEventBus.instance().investment_changed.emit()
                self.refresh()
            else:
                QMessageBox.warning(self, "错误", "\n".join(result.errors))
        finally:
            session.close()

    def _on_edit_trade(self) -> None:
        idx = self._trades_table.currentIndex()
        if not idx.isValid():
            return
        row = idx.row()
        data = self._trades_model._data[row]
        trade_id = data.get("_id")
        if not trade_id:
            return

        dlg = QDialog(self)
        dlg.setWindowTitle("编辑交易")
        fl = QFormLayout(dlg)

        price_spin = QDoubleSpinBox()
        price_spin.setDecimals(4)
        price_spin.setRange(0, 999999999)
        fl.addRow("价格:", price_spin)

        fee_spin = QDoubleSpinBox()
        fee_spin.setDecimals(2)
        fl.addRow("费用:", fee_spin)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        fl.addRow(btns)

        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        session = self._session()
        if not session:
            return
        try:
            svc = StockTradingService(session)
            result = svc.update_trade(
                trade_id,
                price=Decimal(str(price_spin.value())),
                fee=Decimal(str(fee_spin.value())),
            )
            if result.success:
                session.commit()
                self.refresh()
        finally:
            session.close()

    def _on_delete_trade(self) -> None:
        idx = self._trades_table.currentIndex()
        if not idx.isValid():
            return
        row = idx.row()
        data = self._trades_model._data[row]
        trade_id = data.get("_id")
        if not trade_id:
            return

        reply = QMessageBox.question(
            self, "确认删除", "确定要删除该交易记录吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        session = self._session()
        if not session:
            return
        try:
            svc = StockTradingService(session)
            result = svc.delete_trade(trade_id)
            if result.success:
                session.commit()
                AppEventBus.instance().investment_changed.emit()
                self.refresh()
        finally:
            session.close()

    def _on_preview_settlement(self) -> None:
        acct_id = self._get_active_account_id()
        if not acct_id:
            return
        session = self._session()
        if not session:
            return
        try:
            svc = SettlementService(session)
            preview = svc.preview(
                acct_id, self._settle_year.value(), self._settle_month.value()
            )
            msg = (
                f"月结预览 {preview.year}-{preview.month:02d}:\n"
                f"期初资产: ¥{preview.start_total_assets:,.2f}\n"
                f"期末资产: ¥{preview.end_total_assets:,.2f}\n"
                f"净流入: ¥{preview.net_inflow:,.2f}\n"
                f"已实现盈亏: ¥{preview.realized_pnl:,.2f}\n"
                f"股息: ¥{preview.dividend_income:,.2f}\n"
                f"净利润: ¥{preview.net_profit:,.2f}"
            )
            QMessageBox.information(self, "月结预览", msg)
        finally:
            session.close()

    def _on_generate_settlement(self) -> None:
        acct_id = self._get_active_account_id()
        if not acct_id:
            return
        session = self._session()
        if not session:
            return
        try:
            svc = SettlementService(session)
            result = svc.generate(
                acct_id, self._settle_year.value(), self._settle_month.value()
            )
            if result.success:
                session.commit()
                AppEventBus.instance().investment_changed.emit()
                self.refresh()
                QMessageBox.information(self, "成功", "月结已生成")
            else:
                QMessageBox.warning(self, "错误", "\n".join(result.errors))
        finally:
            session.close()

    def _on_void_settlement(self) -> None:
        idx = self._settlement_table.currentIndex()
        if not idx.isValid():
            QMessageBox.information(self, "提示", "请先选择一条月结记录")
            return
        row = idx.row()
        data = self._settlement_model._data[row]
        settlement_id = data.get("_id")

        reply = QMessageBox.question(
            self, "确认作废", "确定要作废该月结记录吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        session = self._session()
        if not session:
            return
        try:
            svc = SettlementService(session)
            result = svc.void_settlement(settlement_id)
            if result.success:
                session.commit()
                self.refresh()
        finally:
            session.close()

    def _on_hide_account(self) -> None:
        self._change_status("hide")

    def _on_show_account(self) -> None:
        self._change_status("show")

    def _on_archive_account(self) -> None:
        self._change_status("archive")

    def _change_status(self, action: str) -> None:
        idx = self._acct_combo.currentIndex()
        if idx < 0:
            return
        acct_id = self._acct_combo.currentData()

        session = self._session()
        if not session:
            return
        try:
            svc = InvestmentService(session)
            if action == "hide":
                result = svc.hide_account(acct_id)
            elif action == "show":
                result = svc.show_account(acct_id)
            else:
                result = svc.archive_account(acct_id)
            if result.success:
                session.commit()
                AppEventBus.instance().module_visibility_changed.emit()
                self.refresh()
        finally:
            session.close()
