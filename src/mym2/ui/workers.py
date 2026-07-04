"""后台任务 worker。

Worker 只接收普通 DTO，不保存或访问 Qt 控件；需要数据库时在 worker 线程内
独立创建并关闭 Engine/Session。
"""

from __future__ import annotations

import csv
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal, Slot
from sqlalchemy.orm import Session

from mym2.db.engine import create_mym2_engine
from mym2.repositories.transaction_repo import TransactionFilter, TransactionRepository
from mym2.services.report_service import ReportFilter, ReportKind, ReportService

TX_TYPE_LABELS: dict[str, str] = {
    'expense': '支出',
    'income': '收入',
    'transfer': '转账',
    'receivable_advance': '应收垫付',
    'receivable_repayment': '应收还款',
    'balance_adjustment': '余额调节',
    'historical_investment_settlement': '历史投资结算',
}

_FORMULA_TRIGGERS = frozenset({'=', '+', '-', '@'})


def _minor_to_yuan(minor: int) -> str:
    sign = '-' if minor < 0 else ''
    val = abs(minor)
    return f'{sign}{val // 100}.{val % 100:02d}'


def _protect_cell(value: str) -> str:
    if value and value[0] in _FORMULA_TRIGGERS:
        return f"'{value}"
    return value


@dataclass(frozen=True, slots=True)
class TransactionExportRequest:
    """流水导出请求 DTO。"""

    db_path: str
    output_path: str
    filters: TransactionFilter
    sort_column: str = 'transaction_date'
    sort_desc: bool = True


@dataclass(frozen=True, slots=True)
class ReportExportRequest:
    """报表导出请求 DTO。"""

    db_path: str
    output_path: str
    kind: ReportKind
    filters: ReportFilter
    format: str


@dataclass(frozen=True, slots=True)
class WorkerResult:
    """后台任务完成结果。"""

    output_path: str
    row_count: int = 0


class BaseWorker(QObject):
    """后台任务基类。"""

    finished = Signal(object)
    failed = Signal(str)

    @Slot()
    def run(self) -> None:
        try:
            self.finished.emit(self.do_work())
        except Exception as exc:
            self.failed.emit(str(exc))

    def do_work(self) -> WorkerResult:
        raise NotImplementedError


class TransactionExportWorker(BaseWorker):
    """导出流水 CSV。"""

    def __init__(self, request: TransactionExportRequest) -> None:
        super().__init__()
        self.request = request

    def do_work(self) -> WorkerResult:
        engine = create_mym2_engine(Path(self.request.db_path))
        try:
            with Session(engine) as session:
                repo = TransactionRepository(session)
                result = repo.query_filtered(
                    self.request.filters,
                    page=1,
                    page_size=max(repo.count_filtered(self.request.filters), 1),
                    sort_column=self.request.sort_column,
                    sort_desc=self.request.sort_desc,
                )
                accounts = repo.get_accounts_map()
                categories = repo.get_categories_map()
                with Path(self.request.output_path).open(
                    'w', newline='', encoding='utf-8-sig'
                ) as fh:
                    writer = csv.writer(fh)
                    writer.writerow([
                        '日期', '类型', '来源账户', '目标账户', '分类',
                        '金额', '备注', '已清算', '锁定', '来源',
                    ])
                    for tx in result.items:
                        acct_out = accounts.get(tx.account_out_id)
                        acct_in = (
                            accounts.get(tx.account_in_id) if tx.account_in_id else None
                        )
                        cat = categories.get(tx.category_id) if tx.category_id else None
                        writer.writerow([
                            str(tx.transaction_date),
                            TX_TYPE_LABELS.get(tx.type, tx.type),
                            acct_out.name if acct_out else tx.account_out_id,
                            acct_in.name if acct_in else '',
                            cat.name if cat else '',
                            _minor_to_yuan(tx.amount_minor),
                            _protect_cell(tx.note or ''),
                            '是' if tx.is_cleared else '否',
                            '是' if tx.is_locked else '否',
                            tx.source or 'manual',
                        ])
                return WorkerResult(self.request.output_path, result.total)
        finally:
            engine.dispose()


class ReportExportWorker(BaseWorker):
    """查询并导出报表。"""

    def __init__(self, request: ReportExportRequest) -> None:
        super().__init__()
        self.request = request

    def do_work(self) -> WorkerResult:
        service = ReportService()
        engine = create_mym2_engine(Path(self.request.db_path))
        try:
            with Session(engine) as session:
                result = service.query(session, self.request.kind, self.request.filters)
            if self.request.format == 'csv':
                service.export_csv(result, self.request.output_path)
            elif self.request.format == 'excel':
                service.export_excel(result, self.request.output_path)
            elif self.request.format == 'pdf':
                service.export_pdf(result, self.request.output_path)
            else:
                raise ValueError(f'未知导出格式: {self.request.format}')
            return WorkerResult(self.request.output_path, len(result.rows))
        finally:
            engine.dispose()


def start_worker(
    worker: BaseWorker,
    *,
    on_finished: Callable[[WorkerResult], None],
    on_failed: Callable[[str], None],
) -> QThread:
    """启动 worker 并返回线程对象，调用方需持有引用。"""
    thread = QThread()
    thread._mym2_worker = worker  # type: ignore[attr-defined]
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    worker.finished.connect(on_finished)
    worker.failed.connect(on_failed)
    worker.finished.connect(thread.quit)
    worker.failed.connect(thread.quit)
    thread.finished.connect(worker.deleteLater)
    thread.finished.connect(thread.deleteLater)
    thread.start()
    return thread
