"""Schema 确保工具 — 在 Alembic 迁移后补充确保列存在（幂等）。

用于绕过 Alembic SQLite 批量模式的限制。
"""

from __future__ import annotations

import logging

from sqlalchemy import Engine, text

logger = logging.getLogger('mym2.db.ensure_schema')


def ensure_budget_columns(engine: Engine) -> None:
    """确保 budget_periods / budget_lines 扩展列存在（幂等）。"""
    with engine.connect() as conn:
        # Check budget_periods columns
        result = conn.execute(text("PRAGMA table_info('budget_periods')"))
        existing_bp = {row[1] for row in result}
        if 'is_closed' not in existing_bp:
            conn.execute(
                text(
                    'ALTER TABLE budget_periods ADD COLUMN is_closed BOOLEAN DEFAULT 0'
                )
            )
            conn.commit()
            logger.info('已添加 budget_periods.is_closed 列')

        # Check budget_lines columns
        result = conn.execute(text("PRAGMA table_info('budget_lines')"))
        existing_bl = {row[1] for row in result}

        cols_to_add = [
            ('type', "VARCHAR(20) DEFAULT 'expense'"),
            ('threshold_minor', 'INTEGER'),
            ('sort_order', 'INTEGER DEFAULT 0'),
        ]
        for col_name, col_def in cols_to_add:
            if col_name not in existing_bl:
                conn.execute(
                    text(
                        f'ALTER TABLE budget_lines '
                        f'ADD COLUMN {col_name} {col_def}'
                    )
                )
                conn.commit()
                logger.info(f'已添加 budget_lines.{col_name} 列')

        # "group" is a reserved word, needs special quoting
        if 'group' not in existing_bl:
            conn.execute(
                text(
                    'ALTER TABLE budget_lines '
                    'ADD COLUMN "group" VARCHAR(50)'
                )
            )
            conn.commit()
            logger.info('已添加 budget_lines.group 列')
