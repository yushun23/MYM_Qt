"""统一报表服务。

所有报表从同一个 ``ReportService.query`` 入口取数，UI、仪表盘、导出和打印
共享同一套口径。服务只做只读查询和文件导出，不修改账本数据。

口径：
- 日常收支只统计 ``expense`` / ``income``，排除余额调节、历史投资结算和应收本金。
- 预算执行只基于已分类的 ``expense``。
- 总资产/净资产包含历史投资资产快照，但不提供任何股票功能。
"""

from __future__ import annotations

import csv
import html
import logging
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

from openpyxl import Workbook
from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.orm import Session

from mym2.db.models.account import Account
from mym2.db.models.budget import BudgetLine, BudgetPeriod
from mym2.db.models.category import Category
from mym2.db.models.transaction import Transaction
from mym2.domain.enums import (
    AccountType,
    TransactionType,
    is_asset_account,
)

logger = logging.getLogger('mym2.services.report_service')

ReportKind = Literal[
    'category_income_expense',
    'monthly_income_expense',
    'asset_liability',
    'receivable_summary',
    'budget_execution',
    'transaction_detail',
]

REPORT_TITLES: dict[str, str] = {
    'category_income_expense': '收支按分类',
    'monthly_income_expense': '月度收支',
    'asset_liability': '账户余额/资产负债',
    'receivable_summary': '应收汇总',
    'budget_execution': '预算执行',
    'transaction_detail': '交易明细导出',
}

DAILY_REPORT_TYPES = frozenset({
    TransactionType.EXPENSE.value,
    TransactionType.INCOME.value,
})

_FORMULA_TRIGGERS = frozenset({'=', '+', '-', '@'})


@dataclass(slots=True)
class ReportFilter:
    """报表筛选条件。"""

    start_date: date
    end_date: date
    account_ids: list[str] = field(default_factory=list)
    category_ids: list[str] = field(default_factory=list)

    def validate(self) -> None:
        if self.start_date > self.end_date:
            raise ValueError('开始日期不能晚于结束日期')


@dataclass(slots=True)
class ReportColumn:
    """报表列定义。"""

    key: str
    title: str
    kind: str = 'text'


@dataclass(slots=True)
class ReportResult:
    """统一报表结果。"""

    kind: str
    title: str
    filters: ReportFilter
    columns: list[ReportColumn]
    rows: list[dict[str, Any]]
    summary: dict[str, int] = field(default_factory=dict)
    scope_note: str = ''


@dataclass(slots=True)
class DashboardData:
    """仪表盘聚合数据。"""

    total_assets_minor: int
    total_liabilities_minor: int
    net_worth_minor: int
    receivable_minor: int
    current_month_income_minor: int
    current_month_expense_minor: int
    budget_total_minor: int | None
    budget_spent_minor: int | None
    asset_accounts: list[tuple[str, int]]
    liability_accounts: list[tuple[str, int]]
    monthly_trend: list[MonthlySnapshot]
    category_breakdown: list[tuple[str, int]]


@dataclass(slots=True)
class MonthlySnapshot:
    """月度快照。"""

    year: int
    month: int
    income_minor: int
    expense_minor: int
    net_worth_minor: int

    @property
    def label(self) -> str:
        return f'{self.month}月'


class ReportService:
    """报表聚合服务（只读）。"""

    def query(
        self,
        session: Session,
        kind: ReportKind,
        filters: ReportFilter,
    ) -> ReportResult:
        """按统一入口查询报表。"""
        filters.validate()
        if kind == 'category_income_expense':
            return self._category_income_expense(session, filters)
        if kind == 'monthly_income_expense':
            return self._monthly_income_expense(session, filters)
        if kind == 'asset_liability':
            return self._asset_liability(session, filters)
        if kind == 'receivable_summary':
            return self._receivable_summary(session, filters)
        if kind == 'budget_execution':
            return self._budget_execution(session, filters)
        if kind == 'transaction_detail':
            return self._transaction_detail(session, filters)
        raise ValueError(f'未知报表类型: {kind}')

    def get_dashboard_data(self, session: Session) -> DashboardData:
        """获取仪表盘所需全部聚合数据。"""
        today = date.today()
        current_filter = ReportFilter(
            start_date=date(today.year, today.month, 1),
            end_date=today,
        )

        balance = self.query(session, 'asset_liability', current_filter)
        month = self.query(session, 'monthly_income_expense', current_filter)
        category = self.query(session, 'category_income_expense', current_filter)
        budget = self.query(session, 'budget_execution', current_filter)

        trend_filter = ReportFilter(
            start_date=_shift_month(date(today.year, today.month, 1), -5),
            end_date=today,
        )
        trend_report = self.query(session, 'monthly_income_expense', trend_filter)
        trend_rows = {
            (int(row['year']), int(row['month'])): row
            for row in trend_report.rows
        }
        monthly_trend = [
            MonthlySnapshot(
                year=year,
                month=month,
                income_minor=int(trend_rows.get((year, month), {}).get('income_minor', 0)),
                expense_minor=int(trend_rows.get((year, month), {}).get('expense_minor', 0)),
                net_worth_minor=balance.summary['net_worth_minor'],
            )
            for year, month in _months_between(trend_filter.start_date, trend_filter.end_date)
        ]

        asset_accounts = [
            (str(row['account_name']), int(row['balance_minor']))
            for row in balance.rows
            if row['side'] == 'asset'
        ]
        liability_accounts = [
            (str(row['account_name']), int(row['balance_minor']))
            for row in balance.rows
            if row['side'] == 'liability'
        ]
        current_month_row = month.rows[-1] if month.rows else {}
        budget_total = budget.summary.get('budget_total_minor')
        budget_spent = budget.summary.get('actual_total_minor')

        return DashboardData(
            total_assets_minor=balance.summary['total_assets_minor'],
            total_liabilities_minor=balance.summary['total_liabilities_minor'],
            net_worth_minor=balance.summary['net_worth_minor'],
            receivable_minor=balance.summary['receivable_minor'],
            current_month_income_minor=int(current_month_row.get('income_minor', 0)),
            current_month_expense_minor=int(current_month_row.get('expense_minor', 0)),
            budget_total_minor=budget_total if budget.rows else None,
            budget_spent_minor=budget_spent if budget.rows else None,
            asset_accounts=asset_accounts,
            liability_accounts=liability_accounts,
            monthly_trend=monthly_trend,
            category_breakdown=[
                (str(row['category_name']), int(row['expense_minor']))
                for row in category.rows
                if int(row['expense_minor']) > 0
            ][:10],
        )

    def export_csv(self, result: ReportResult, path: str | Path) -> None:
        """导出报表为 UTF-8 with BOM CSV。"""
        with Path(path).open('w', newline='', encoding='utf-8-sig') as fh:
            writer = csv.writer(fh)
            writer.writerow([col.title for col in result.columns])
            for row in result.rows:
                writer.writerow([
                    _protect_cell(_format_cell(row.get(col.key), col.kind))
                    for col in result.columns
                ])

    def export_excel(self, result: ReportResult, path: str | Path) -> None:
        """导出报表为 Excel。"""
        wb = Workbook()
        ws = wb.active
        ws.title = _safe_sheet_title(result.title)
        ws.append([col.title for col in result.columns])
        for row in result.rows:
            ws.append([_format_cell(row.get(col.key), col.kind) for col in result.columns])
        for col_idx, column in enumerate(result.columns, start=1):
            ws.column_dimensions[chr(64 + col_idx)].width = max(12, len(column.title) + 4)
        wb.save(path)

    def build_print_html(self, result: ReportResult) -> str:
        """构建离线 PDF 打印 HTML。"""
        headers = ''.join(f'<th>{html.escape(col.title)}</th>' for col in result.columns)
        rows = []
        for row in result.rows:
            cells = ''.join(
                (
                    f'<td class="{col.kind}">'
                    f'{html.escape(_format_cell(row.get(col.key), col.kind))}</td>'
                )
                for col in result.columns
            )
            rows.append(f'<tr>{cells}</tr>')
        summary_items = ''.join(
            f'<span>{html.escape(_summary_label(k))}: {html.escape(_format_minor(v))}</span>'
            for k, v in result.summary.items()
        )
        return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<style>
body {{
  font-family: -apple-system, BlinkMacSystemFont, "Microsoft YaHei", sans-serif;
  color: #222;
}}
h1 {{ font-size: 22px; margin: 0 0 6px; }}
.meta, .note {{ color: #555; font-size: 12px; margin: 4px 0 12px; }}
.summary {{ display: flex; gap: 14px; flex-wrap: wrap; margin: 10px 0; font-size: 13px; }}
table {{ border-collapse: collapse; width: 100%; font-size: 11px; }}
th, td {{ border: 1px solid #bbb; padding: 5px 6px; text-align: left; }}
th {{ background: #f0f2f5; }}
td.money, td.integer, td.percent {{ text-align: right; }}
</style>
</head>
<body>
<h1>{html.escape(result.title)}</h1>
<div class="meta">日期区间：{result.filters.start_date.isoformat()}
至 {result.filters.end_date.isoformat()}</div>
<div class="note">{html.escape(result.scope_note)}</div>
<div class="summary">{summary_items}</div>
<table><thead><tr>{headers}</tr></thead><tbody>{''.join(rows)}</tbody></table>
</body>
</html>"""

    def export_pdf(self, result: ReportResult, path: str | Path) -> None:
        """使用 Qt QTextDocument + QPdfWriter 离线打印 PDF。"""
        from PySide6.QtCore import QMarginsF
        from PySide6.QtGui import QPageLayout, QPageSize, QPdfWriter, QTextDocument

        writer = QPdfWriter(str(path))
        writer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
        writer.setPageMargins(QMarginsF(12, 12, 12, 12), QPageLayout.Unit.Millimeter)
        writer.setResolution(96)
        doc = QTextDocument()
        doc.setHtml(self.build_print_html(result))
        doc.print_(writer)

    # ── 报表构建 ───────────────────────────────────

    def _category_income_expense(
        self, session: Session, filters: ReportFilter
    ) -> ReportResult:
        scoped = self._daily_transaction_select(filters)
        subq = scoped.subquery()
        rows = session.execute(
            select(
                func.coalesce(Category.name, '未分类').label('category_name'),
                func.coalesce(Category.type, '').label('category_type'),
                func.coalesce(
                    func.sum(
                        case(
                            (subq.c.type == TransactionType.INCOME.value, subq.c.amount_minor),
                            else_=0,
                        )
                    ),
                    0,
                ).label('income_minor'),
                func.coalesce(
                    func.sum(
                        case(
                            (subq.c.type == TransactionType.EXPENSE.value, subq.c.amount_minor),
                            else_=0,
                        )
                    ),
                    0,
                ).label('expense_minor'),
            )
            .select_from(subq)
            .outerjoin(Category, subq.c.category_id == Category.id)
            .group_by(Category.name, Category.type)
            .order_by(func.coalesce(func.sum(subq.c.amount_minor), 0).desc())
        ).all()
        data = [
            {
                'category_name': row.category_name,
                'category_type': _category_type_label(row.category_type),
                'income_minor': int(row.income_minor),
                'expense_minor': int(row.expense_minor),
                'net_minor': int(row.income_minor) - int(row.expense_minor),
            }
            for row in rows
        ]
        return ReportResult(
            kind='category_income_expense',
            title=REPORT_TITLES['category_income_expense'],
            filters=filters,
            columns=[
                ReportColumn('category_name', '分类'),
                ReportColumn('category_type', '类型'),
                ReportColumn('income_minor', '收入', 'money'),
                ReportColumn('expense_minor', '支出', 'money'),
                ReportColumn('net_minor', '净额', 'money'),
            ],
            rows=data,
            summary={
                'income_minor': sum(int(row['income_minor']) for row in data),
                'expense_minor': sum(int(row['expense_minor']) for row in data),
            },
            scope_note=_daily_scope_note(),
        )

    def _monthly_income_expense(
        self, session: Session, filters: ReportFilter
    ) -> ReportResult:
        scoped = self._daily_transaction_select(filters)
        subq = scoped.subquery()
        rows = session.execute(
            select(
                func.strftime('%Y', subq.c.transaction_date).label('year'),
                func.strftime('%m', subq.c.transaction_date).label('month'),
                func.coalesce(
                    func.sum(
                        case(
                            (subq.c.type == TransactionType.INCOME.value, subq.c.amount_minor),
                            else_=0,
                        )
                    ),
                    0,
                ).label('income_minor'),
                func.coalesce(
                    func.sum(
                        case(
                            (subq.c.type == TransactionType.EXPENSE.value, subq.c.amount_minor),
                            else_=0,
                        )
                    ),
                    0,
                ).label('expense_minor'),
            )
            .select_from(subq)
            .group_by('year', 'month')
            .order_by('year', 'month')
        ).all()
        data = [
            {
                'year': int(row.year),
                'month': int(row.month),
                'period': f'{int(row.year)}-{int(row.month):02d}',
                'income_minor': int(row.income_minor),
                'expense_minor': int(row.expense_minor),
                'net_minor': int(row.income_minor) - int(row.expense_minor),
            }
            for row in rows
        ]
        return ReportResult(
            kind='monthly_income_expense',
            title=REPORT_TITLES['monthly_income_expense'],
            filters=filters,
            columns=[
                ReportColumn('period', '月份'),
                ReportColumn('income_minor', '收入', 'money'),
                ReportColumn('expense_minor', '支出', 'money'),
                ReportColumn('net_minor', '净额', 'money'),
            ],
            rows=data,
            summary={
                'income_minor': sum(int(row['income_minor']) for row in data),
                'expense_minor': sum(int(row['expense_minor']) for row in data),
            },
            scope_note=_daily_scope_note(),
        )

    def _asset_liability(self, session: Session, filters: ReportFilter) -> ReportResult:
        stmt = select(Account).where(Account.is_enabled.is_(True))
        if filters.account_ids:
            stmt = stmt.where(Account.id.in_(filters.account_ids))
        accounts = list(session.scalars(stmt.order_by(Account.type, Account.name)))
        data = []
        for account in accounts:
            side = 'asset' if is_asset_account(account.type) else 'liability'
            data.append({
                'account_name': account.name,
                'account_type': _account_type_label(account.type),
                'side': side,
                'side_label': '资产' if side == 'asset' else '负债',
                'balance_minor': int(account.current_balance_minor),
                'editable_label': '是' if account.is_editable else '否',
            })
        total_assets = sum(
            int(row['balance_minor']) for row in data if row['side'] == 'asset'
        )
        total_liabilities = sum(
            int(row['balance_minor']) for row in data if row['side'] == 'liability'
        )
        receivable = sum(
            int(account.current_balance_minor)
            for account in accounts
            if account.type == AccountType.RECEIVABLE.value
        )
        return ReportResult(
            kind='asset_liability',
            title=REPORT_TITLES['asset_liability'],
            filters=filters,
            columns=[
                ReportColumn('account_name', '账户'),
                ReportColumn('account_type', '账户类型'),
                ReportColumn('side_label', '资产/负债'),
                ReportColumn('balance_minor', '当前余额', 'money'),
                ReportColumn('editable_label', '可编辑'),
            ],
            rows=data,
            summary={
                'total_assets_minor': total_assets,
                'total_liabilities_minor': total_liabilities,
                'net_worth_minor': total_assets - total_liabilities,
                'receivable_minor': receivable,
            },
            scope_note=(
                '资产负债报表使用当前账户余额；历史投资资产快照仅作为不可编辑历史估值计入净资产，'
                '不提供持仓、行情、买卖等股票功能。'
            ),
        )

    def _receivable_summary(self, session: Session, filters: ReportFilter) -> ReportResult:
        advance = self._sum_by_account_type(
            session, filters, TransactionType.RECEIVABLE_ADVANCE.value
        )
        repayment = self._sum_by_account_type(
            session, filters, TransactionType.RECEIVABLE_REPAYMENT.value
        )
        stmt = select(Account).where(
            Account.type == AccountType.RECEIVABLE.value,
            Account.is_enabled.is_(True),
        )
        if filters.account_ids:
            stmt = stmt.where(Account.id.in_(filters.account_ids))
        accounts = list(session.scalars(stmt.order_by(Account.name)))
        data = [
            {
                'account_name': account.name,
                'advanced_minor': advance.get(account.id, 0),
                'repaid_minor': repayment.get(account.id, 0),
                'balance_minor': int(account.current_balance_minor),
                'status': '未结清' if account.current_balance_minor > 0 else '已结清',
            }
            for account in accounts
        ]
        return ReportResult(
            kind='receivable_summary',
            title=REPORT_TITLES['receivable_summary'],
            filters=filters,
            columns=[
                ReportColumn('account_name', '债务人/应收账户'),
                ReportColumn('advanced_minor', '区间垫付', 'money'),
                ReportColumn('repaid_minor', '区间收回', 'money'),
                ReportColumn('balance_minor', '当前待收', 'money'),
                ReportColumn('status', '状态'),
            ],
            rows=data,
            summary={
                'advanced_minor': sum(int(row['advanced_minor']) for row in data),
                'repaid_minor': sum(int(row['repaid_minor']) for row in data),
                'receivable_minor': sum(int(row['balance_minor']) for row in data),
            },
            scope_note='应收汇总展示本金垫付与收回情况；应收本金不计入日常消费/收入报表。',
        )

    def _budget_execution(self, session: Session, filters: ReportFilter) -> ReportResult:
        periods = _months_between(filters.start_date, filters.end_date)
        data: list[dict[str, Any]] = []
        for year, month in periods:
            period = session.scalar(
                select(BudgetPeriod).where(
                    BudgetPeriod.year == year,
                    BudgetPeriod.month == month,
                )
            )
            if period is None:
                continue
            line_stmt = (
                select(BudgetLine, Category.name)
                .join(Category, BudgetLine.category_id == Category.id)
                .where(BudgetLine.budget_period_id == period.id)
            )
            if filters.category_ids:
                line_stmt = line_stmt.where(BudgetLine.category_id.in_(filters.category_ids))
            for line, category_name in session.execute(line_stmt).all():
                actual = self._sum_expense_for_category(
                    session,
                    year,
                    month,
                    line.category_id,
                    filters.account_ids,
                )
                remaining = int(line.amount_minor) - actual
                progress = (
                    Decimal(actual) * Decimal(100) / Decimal(line.amount_minor)
                    if line.amount_minor
                    else Decimal(0)
                )
                data.append({
                    'period': f'{year}-{month:02d}',
                    'category_name': category_name,
                    'budget_minor': int(line.amount_minor),
                    'actual_minor': actual,
                    'remaining_minor': remaining,
                    'progress_pct': progress.quantize(Decimal('0.1')),
                    'status': '超支' if actual > int(line.amount_minor) else '正常',
                })
        return ReportResult(
            kind='budget_execution',
            title=REPORT_TITLES['budget_execution'],
            filters=filters,
            columns=[
                ReportColumn('period', '月份'),
                ReportColumn('category_name', '分类'),
                ReportColumn('budget_minor', '预算', 'money'),
                ReportColumn('actual_minor', '实际支出', 'money'),
                ReportColumn('remaining_minor', '剩余', 'money'),
                ReportColumn('progress_pct', '执行率', 'percent'),
                ReportColumn('status', '状态'),
            ],
            rows=data,
            summary={
                'budget_total_minor': sum(int(row['budget_minor']) for row in data),
                'actual_total_minor': sum(int(row['actual_minor']) for row in data),
            },
            scope_note=(
                '预算执行仅统计已分类 expense 流水；转账、余额调节、'
                '历史投资结算与应收本金不纳入。'
            ),
        )

    def _transaction_detail(self, session: Session, filters: ReportFilter) -> ReportResult:
        scoped = self._transaction_scope(filters).subquery()
        rows = session.execute(
            select(
                scoped.c.transaction_date,
                scoped.c.type,
                scoped.c.amount_minor,
                scoped.c.note,
                scoped.c.is_cleared,
                scoped.c.is_locked,
                scoped.c.source,
                func.coalesce(Category.name, '').label('category_name'),
                Account.name.label('account_out_name'),
                func.coalesce(AccountIn.c.name, '').label('account_in_name'),
            )
            .select_from(scoped)
            .join(Account, scoped.c.account_out_id == Account.id)
            .outerjoin(AccountIn, scoped.c.account_in_id == AccountIn.c.id)
            .outerjoin(Category, scoped.c.category_id == Category.id)
            .order_by(scoped.c.transaction_date, scoped.c.id)
        ).all()
        data = [
            {
                'transaction_date': row.transaction_date,
                'type_label': _transaction_type_label(row.type),
                'account_out_name': row.account_out_name,
                'account_in_name': row.account_in_name,
                'category_name': row.category_name,
                'amount_minor': int(row.amount_minor),
                'note': row.note or '',
                'cleared_label': '是' if row.is_cleared else '否',
                'locked_label': '是' if row.is_locked else '否',
                'source': row.source or 'manual',
            }
            for row in rows
        ]
        return ReportResult(
            kind='transaction_detail',
            title=REPORT_TITLES['transaction_detail'],
            filters=filters,
            columns=[
                ReportColumn('transaction_date', '日期', 'date'),
                ReportColumn('type_label', '类型'),
                ReportColumn('account_out_name', '来源账户'),
                ReportColumn('account_in_name', '目标账户'),
                ReportColumn('category_name', '分类'),
                ReportColumn('amount_minor', '金额', 'money'),
                ReportColumn('note', '备注'),
                ReportColumn('cleared_label', '已清算'),
                ReportColumn('locked_label', '锁定'),
                ReportColumn('source', '来源'),
            ],
            rows=data,
            summary={'amount_minor': sum(int(row['amount_minor']) for row in data)},
            scope_note='交易明细按筛选条件导出原始流水；历史投资结算只作为历史导入记录展示。',
        )

    # ── 公共查询口径 ───────────────────────────────

    def _transaction_scope(self, filters: ReportFilter):
        clauses = [
            Transaction.transaction_date >= filters.start_date,
            Transaction.transaction_date <= filters.end_date,
        ]
        if filters.account_ids:
            clauses.append(
                or_(
                    Transaction.account_out_id.in_(filters.account_ids),
                    Transaction.account_in_id.in_(filters.account_ids),
                )
            )
        if filters.category_ids:
            clauses.append(Transaction.category_id.in_(filters.category_ids))
        return select(Transaction).where(and_(*clauses))

    def _daily_transaction_select(self, filters: ReportFilter):
        return self._transaction_scope(filters).where(Transaction.type.in_(DAILY_REPORT_TYPES))

    def _sum_by_account_type(
        self, session: Session, filters: ReportFilter, tx_type: str
    ) -> dict[str, int]:
        account_col = (
            Transaction.account_in_id
            if tx_type == TransactionType.RECEIVABLE_ADVANCE.value
            else Transaction.account_out_id
        )
        clauses = [
            Transaction.type == tx_type,
            Transaction.transaction_date >= filters.start_date,
            Transaction.transaction_date <= filters.end_date,
        ]
        if filters.account_ids:
            clauses.append(account_col.in_(filters.account_ids))
        rows = session.execute(
            select(account_col, func.coalesce(func.sum(Transaction.amount_minor), 0))
            .where(and_(*clauses))
            .group_by(account_col)
        ).all()
        return {row[0]: int(row[1]) for row in rows}

    def _sum_expense_for_category(
        self,
        session: Session,
        year: int,
        month: int,
        category_id: str,
        account_ids: list[str],
    ) -> int:
        start = date(year, month, 1)
        end = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
        clauses = [
            Transaction.category_id == category_id,
            Transaction.type == TransactionType.EXPENSE.value,
            Transaction.transaction_date >= start,
            Transaction.transaction_date < end,
        ]
        if account_ids:
            clauses.append(
                or_(
                    Transaction.account_out_id.in_(account_ids),
                    Transaction.account_in_id.in_(account_ids),
                )
            )
        return int(
            session.scalar(
                select(func.coalesce(func.sum(Transaction.amount_minor), 0))
                .where(and_(*clauses))
            )
            or 0
        )


AccountIn = Account.__table__.alias('account_in')


def _format_minor(minor: int) -> str:
    sign = '-' if minor < 0 else ''
    val = abs(int(minor))
    return f'{sign}{val // 100}.{val % 100:02d}'


def _format_cell(value: Any, kind: str) -> str:
    if value is None:
        return ''
    if kind == 'money':
        return _format_minor(int(value))
    if kind == 'date':
        return value.isoformat() if hasattr(value, 'isoformat') else str(value)
    if kind == 'percent':
        return f'{value}%'
    return str(value)


def _protect_cell(value: str) -> str:
    if value and value[0] in _FORMULA_TRIGGERS:
        return f"'{value}"
    return value


def _safe_sheet_title(title: str) -> str:
    for char in '[]:*?/\\':
        title = title.replace(char, '_')
    return title[:31] or 'Report'


def _daily_scope_note() -> str:
    return (
        '日常收支仅统计 expense/income；余额调节、历史投资结算与应收本金不计入消费/收入，'
        '避免把历史估值或借还款本金理解为本月日常收支。'
    )


def _summary_label(key: str) -> str:
    labels = {
        'income_minor': '收入合计',
        'expense_minor': '支出合计',
        'total_assets_minor': '总资产',
        'total_liabilities_minor': '总负债',
        'net_worth_minor': '净资产',
        'receivable_minor': '应收余额',
        'advanced_minor': '垫付合计',
        'repaid_minor': '收回合计',
        'budget_total_minor': '预算合计',
        'actual_total_minor': '实际合计',
        'amount_minor': '金额合计',
    }
    return labels.get(key, key)


def _transaction_type_label(tx_type: str) -> str:
    labels = {
        'expense': '支出',
        'income': '收入',
        'transfer': '转账',
        'receivable_advance': '应收垫付',
        'receivable_repayment': '应收还款',
        'balance_adjustment': '余额调节',
        'historical_investment_settlement': '历史投资结算',
    }
    return labels.get(tx_type, tx_type)


def _account_type_label(account_type: str) -> str:
    labels = {
        'cash': '现金',
        'bank': '银行',
        'credit_card': '信用卡',
        'investment_snapshot': '历史投资资产快照',
        'receivable': '应收',
    }
    return labels.get(account_type, account_type)


def _category_type_label(category_type: str) -> str:
    labels = {'expense': '支出', 'income': '收入', 'system': '系统'}
    return labels.get(category_type, category_type or '未分类')


def _months_between(start: date, end: date) -> list[tuple[int, int]]:
    months = []
    current = date(start.year, start.month, 1)
    last = date(end.year, end.month, 1)
    while current <= last:
        months.append((current.year, current.month))
        current = _shift_month(current, 1)
    return months


def _shift_month(value: date, offset: int) -> date:
    month_index = value.year * 12 + value.month - 1 + offset
    year = month_index // 12
    month = month_index % 12 + 1
    return date(year, month, 1)
