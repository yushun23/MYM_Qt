"""诊断包导出服务。

默认诊断包只包含环境摘要、脱敏日志和非秘密设置；不会包含数据库、完整流水、
密钥、密码或旧库路径。用户显式选择时才可附加数据库副本或完整流水导出。
"""

from __future__ import annotations

import json
import platform
import shutil
import sqlite3
import zipfile
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from mym2.core.logging import redact_text
from mym2.db.models.app_setting import AppSetting
from mym2.db.models.transaction import Transaction
from mym2.services.settings_service import ALLOWED_SETTING_KEYS


@dataclass(frozen=True, slots=True)
class DiagnosticsOptions:
    """诊断包导出选项。"""

    include_database: bool = False
    include_full_transactions: bool = False


@dataclass(frozen=True, slots=True)
class DiagnosticsResult:
    """诊断包导出结果。"""

    path: str
    created_at: str
    included: list[str]


class DiagnosticsService:
    """生成默认脱敏的诊断包。"""

    def export_package(
        self,
        session: Session,
        *,
        destination: str | Path,
        logs_dir: str | Path,
        db_path: str | Path | None = None,
        options: DiagnosticsOptions | None = None,
    ) -> DiagnosticsResult:
        options = options or DiagnosticsOptions()
        destination = Path(destination)
        logs_dir = Path(logs_dir)
        destination.parent.mkdir(parents=True, exist_ok=True)
        created_at = datetime.now(UTC).replace(microsecond=0).isoformat()
        included: list[str] = []

        with zipfile.ZipFile(destination, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
            self._write_json(zf, 'manifest.json', {
                'created_at': created_at,
                'options': asdict(options),
                'privacy_default': (
                    '默认不包含数据库、秘密、完整流水；日志和设置已脱敏。'
                ),
            })
            included.append('manifest.json')

            self._write_json(zf, 'environment.json', self._environment_summary())
            included.append('environment.json')

            self._write_json(zf, 'settings.json', self._safe_settings(session))
            included.append('settings.json')

            schema_summary = self._schema_summary(db_path) if db_path else {}
            self._write_json(zf, 'schema_summary.json', schema_summary)
            included.append('schema_summary.json')

            for log_path in sorted(logs_dir.glob('mym2.log*')) + sorted(
                logs_dir.glob('mym2.jsonl*')
            ):
                if log_path.is_file():
                    zf.writestr(
                        f'logs/{log_path.name}',
                        redact_text(log_path.read_text(encoding='utf-8', errors='replace')),
                    )
                    included.append(f'logs/{log_path.name}')

            if options.include_full_transactions:
                zf.writestr('transactions.json', self._transactions_json(session))
                included.append('transactions.json')

            if options.include_database and db_path:
                db_path = Path(db_path)
                if db_path.exists():
                    tmp_copy = destination.with_suffix('.dbtmp')
                    shutil.copy2(db_path, tmp_copy)
                    try:
                        zf.write(tmp_copy, 'database/mym2.db')
                    finally:
                        tmp_copy.unlink(missing_ok=True)
                    included.append('database/mym2.db')

        return DiagnosticsResult(
            path=str(destination),
            created_at=created_at,
            included=included,
        )

    @staticmethod
    def _write_json(zf: zipfile.ZipFile, name: str, payload: object) -> None:
        zf.writestr(
            name,
            redact_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)),
        )

    @staticmethod
    def _environment_summary() -> dict[str, str]:
        return {
            'python': platform.python_version(),
            'platform': platform.platform(),
            'machine': platform.machine(),
        }

    @staticmethod
    def _safe_settings(session: Session) -> dict[str, str]:
        rows = session.execute(
            select(AppSetting.key, AppSetting.value).where(
                AppSetting.key.in_(ALLOWED_SETTING_KEYS)
            )
        ).all()
        return {str(key): redact_text(str(value)) for key, value in rows}

    @staticmethod
    def _schema_summary(db_path: str | Path | None) -> dict[str, int]:
        if db_path is None:
            return {}
        db_path = Path(db_path)
        if not db_path.exists():
            return {}
        conn = sqlite3.connect(f'{db_path.resolve().as_uri()}?mode=ro', uri=True)
        try:
            rows = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            ).fetchall()
            summary: dict[str, int] = {}
            for (table_name,) in rows:
                if table_name.startswith('sqlite_'):
                    continue
                count = conn.execute(f'SELECT COUNT(*) FROM "{table_name}"').fetchone()[0]
                summary[str(table_name)] = int(count)
            return summary
        finally:
            conn.close()

    @staticmethod
    def _transactions_json(session: Session) -> str:
        rows = session.execute(
            select(
                Transaction.transaction_date,
                Transaction.type,
                Transaction.amount_minor,
                Transaction.source,
                Transaction.is_cleared,
                Transaction.is_locked,
            ).order_by(Transaction.transaction_date, Transaction.id)
        ).all()
        payload = [
            {
                'transaction_date': row.transaction_date.isoformat(),
                'type': row.type,
                'amount_minor': int(row.amount_minor),
                'source': row.source,
                'is_cleared': bool(row.is_cleared),
                'is_locked': bool(row.is_locked),
            }
            for row in rows
        ]
        return redact_text(json.dumps(payload, ensure_ascii=False, indent=2))
