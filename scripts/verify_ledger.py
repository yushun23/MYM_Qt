#!/usr/bin/env python3
"""Verify ledger integrity: foreign keys, transaction conservation, balance consistency."""

import sys
from decimal import Decimal
from pathlib import Path

from mym.infrastructure.database.db_manager import DatabaseManager
from mym.domain.enums import TransactionStatus

def verify(ledger_path: str) -> int:
    """Return 0 if healthy, non-zero otherwise."""
    mgr = DatabaseManager(Path(ledger_path))
    try:
        mgr.open(apply_migrations=False)
    except Exception as e:
        print(f"ERROR: Cannot open ledger: {e}")
        return 1

    session = mgr.new_session()
    issues = 0

    try:
        # Health check
        report = mgr.health_check()
        if not report.is_healthy:
            print("Health check FAILED:")
            for issue in report.issues:
                print(f"  - {issue}")
                issues += 1
        else:
            print("Health check: PASSED")

        # Transaction conservation
        from sqlalchemy import text
        rows = session.execute(text("""
            SELECT t.id, t.business_type,
                   SUM(CASE WHEN tl.role='debit' THEN tl.signed_amount ELSE 0 END) as debits,
                   SUM(CASE WHEN tl.role='credit' THEN tl.signed_amount ELSE 0 END) as credits
            FROM transactions t
            JOIN transaction_lines tl ON tl.transaction_id = t.id
            WHERE t.status != 'void'
            GROUP BY t.id
        """)).fetchall()

        for row in rows:
            diff = abs(Decimal(str(row[1] or 0)) - Decimal(str(row[2] or 0)))
            if diff > Decimal("0.01"):
                print(f"CONSERVATION ERROR: tx_id={row[0]} type={row[1]} debits={row[2]} credits={row[3]}")
                issues += 1

        if issues == 0:
            print("Transaction conservation: PASSED")
    finally:
        session.close()
        mgr.close()

    return 0 if issues == 0 else 1


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python verify_ledger.py <ledger_path>")
        sys.exit(1)
    sys.exit(verify(sys.argv[1]))
