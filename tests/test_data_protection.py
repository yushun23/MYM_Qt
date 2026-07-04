"""设置、备份恢复、安全与可选 AI 验收测试。"""

from __future__ import annotations

import logging
import sqlite3
from datetime import date
from pathlib import Path

import pytest
from keyring.errors import NoKeyringError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from mym2.core.logging import setup_logging
from mym2.db.migrate import upgrade_to_head
from mym2.db.models.account import Account
from mym2.db.models.app_setting import AppSetting
from mym2.db.models.audit_event import AuditEvent
from mym2.db.models.category import Category
from mym2.db.models.transaction import Transaction
from mym2.domain.enums import AccountType, CategoryType, TransactionType
from mym2.services.ai_assistant_service import (
    AIAssistantService,
    AICredentialStore,
    AITransactionDraft,
)
from mym2.services.backup_service import (
    RESTORE_CONFIRMATION,
    BackupService,
)
from mym2.services.settings_service import SettingsService


def _create_sqlite_db(path: Path, theme: str) -> None:
    upgrade_to_head(path)
    conn = sqlite3.connect(str(path))
    try:
        conn.execute(
            'INSERT INTO app_settings (id, key, value) VALUES (?, ?, ?)',
            ('setting-theme', 'theme', theme),
        )
        conn.commit()
    finally:
        conn.close()


def _read_theme(path: Path) -> str:
    conn = sqlite3.connect(str(path))
    try:
        row = conn.execute(
            "SELECT value FROM app_settings WHERE key = 'theme'"
        ).fetchone()
        return row[0]
    finally:
        conn.close()


def _seed_ai_ledger(session: Session) -> tuple[Account, Category]:
    account = Account(
        name='现金',
        type=AccountType.CASH,
        is_enabled=True,
        is_editable=True,
        is_locked=False,
        opening_balance_minor=10_000,
        current_balance_minor=10_000,
        currency='CNY',
    )
    category = Category(
        name='餐饮',
        type=CategoryType.EXPENSE,
        is_enabled=True,
    )
    session.add_all([account, category])
    session.commit()
    return account, category


class TestSettingsProtection:
    def test_app_settings_allow_only_non_secret_preferences(
        self, session: Session
    ) -> None:
        service = SettingsService()
        service.set(session, 'theme', 'dark')
        service.set(session, 'backup_retention_count', '7')
        service.set(session, 'ai_enabled', 'false')

        for forbidden in ('api_key', 'password_hash', 'proxy_password'):
            with pytest.raises(ValueError):
                service.set(session, forbidden, 'sensitive-value')

        session.commit()
        keys = session.scalars(select(AppSetting.key)).all()
        assert 'theme' in keys
        assert 'api_key' not in keys
        assert 'password_hash' not in keys

    def test_ai_defaults_to_disabled(self, session: Session) -> None:
        settings = AIAssistantService().get_settings(session)
        assert settings.enabled is False


class TestBackupRestore:
    def test_backup_verify_restore_and_retention(self, tmp_path: Path) -> None:
        db_path = tmp_path / 'mym2.db'
        backup_dir = tmp_path / 'backups'
        _create_sqlite_db(db_path, 'dark')

        service = BackupService()
        first = service.create_backup(
            db_path, backup_dir, reason='manual', retention_count=1
        )
        assert len(first.sha256) == 64
        assert service.verify_backup(
            backup_dir / first.filename, expected_sha256=first.sha256
        ) == first.sha256

        conn = sqlite3.connect(str(db_path))
        try:
            conn.execute("UPDATE app_settings SET value = 'light' WHERE key = 'theme'")
            conn.commit()
        finally:
            conn.close()
        assert _read_theme(db_path) == 'light'

        result = service.restore_backup(
            backup_dir / first.filename,
            db_path,
            expected_sha256=first.sha256,
            confirmation_text=RESTORE_CONFIRMATION,
        )
        assert result.restart_required is True
        assert _read_theme(db_path) == 'dark'

        second = service.create_backup(
            db_path, backup_dir, reason='manual', retention_count=1
        )
        manifest = service.load_manifest(backup_dir)
        assert [item.filename for item in manifest] == [second.filename]
        assert not (backup_dir / first.filename).exists()

    def test_restore_requires_explicit_confirmation(self, tmp_path: Path) -> None:
        db_path = tmp_path / 'mym2.db'
        backup_dir = tmp_path / 'backups'
        _create_sqlite_db(db_path, 'dark')
        service = BackupService()
        metadata = service.create_backup(db_path, backup_dir)

        with pytest.raises(PermissionError):
            service.restore_backup(
                backup_dir / metadata.filename,
                db_path,
                expected_sha256=metadata.sha256,
                confirmation_text='yes',
            )


class TestRedactedLogging:
    def test_logs_redact_secrets_and_paths(self, tmp_path: Path) -> None:
        logger = setup_logging(tmp_path, level=logging.INFO)
        logger.info(
            'path=/Users/example/private/mym2.db api_key=secret note=午餐'
        )
        for handler in logger.handlers:
            handler.flush()

        text = (tmp_path / 'mym2.log').read_text(encoding='utf-8')
        assert 'api_key=secret' not in text
        assert '/Users/example/private/mym2.db' not in text
        assert '<redacted>' in text
        assert '<path>' in text


class TestAIAssistant:
    def test_keyring_missing_uses_session_only_and_never_db(
        self, monkeypatch: pytest.MonkeyPatch, session: Session
    ) -> None:
        def _raise_no_keyring(*args, **kwargs):
            raise NoKeyringError('no keyring')

        monkeypatch.setattr('keyring.set_password', _raise_no_keyring)
        monkeypatch.setattr('keyring.get_password', _raise_no_keyring)

        store = AICredentialStore()
        result = store.set_api_key('test-provider', 'session-only-value')
        assert result.persisted is False
        assert result.session_only is True
        assert store.get_api_key('test-provider') == 'session-only-value'

        values = session.scalars(select(AppSetting.value)).all()
        assert 'session-only-value' not in values

    def test_reject_confirmation_leaves_database_unchanged(
        self, session: Session
    ) -> None:
        account, category = _seed_ai_ledger(session)
        draft = AITransactionDraft(
            transaction_type=TransactionType.EXPENSE,
            transaction_date=date(2026, 7, 4),
            account_out_id=account.id,
            category_id=category.id,
            amount_minor=1200,
            note='AI draft',
            estimated_impact='现金 -12.00',
        )

        service = AIAssistantService()
        before = session.scalar(select(func.count(Transaction.id)))
        tx = service.confirm_draft(session, draft, confirmed=False)
        session.commit()
        after = session.scalar(select(func.count(Transaction.id)))

        assert tx is None
        assert after == before

    def test_confirmed_ai_draft_writes_via_ledger_service(
        self, session: Session
    ) -> None:
        account, category = _seed_ai_ledger(session)
        draft = AITransactionDraft(
            transaction_type=TransactionType.EXPENSE,
            transaction_date=date(2026, 7, 4),
            account_out_id=account.id,
            category_id=category.id,
            amount_minor=1200,
            note='AI draft',
            estimated_impact='现金 -12.00',
        )

        tx = AIAssistantService().confirm_draft(session, draft, confirmed=True)
        session.commit()

        assert tx is not None
        assert tx.source == 'ai'
        session.refresh(account)
        assert account.current_balance_minor == 8800
        audit_count = session.scalar(
            select(func.count(AuditEvent.id)).where(AuditEvent.entity_id == tx.id)
        )
        assert audit_count == 1

    def test_context_is_minimized_and_requires_confirmation(
        self, session: Session
    ) -> None:
        account, category = _seed_ai_ledger(session)
        service = AIAssistantService()

        with pytest.raises(PermissionError):
            service.build_minimized_context(
                user_scope='本月餐饮',
                confirmed=False,
                accounts=[account],
                categories=[category],
            )

        context = service.build_minimized_context(
            user_scope='本月餐饮',
            confirmed=True,
            accounts=[account],
            categories=[category],
            recent_transactions=[{
                'transaction_date': '2026-07-04',
                'type': 'expense',
                'amount_minor': 1200,
                'account_out_id': account.id,
                'category_id': category.id,
                'note': '不要默认上传备注',
            }],
        )
        assert context['accounts'][0]['id'] == account.id
        assert 'name' not in context['accounts'][0]
        assert 'note' not in context['transactions'][0]
