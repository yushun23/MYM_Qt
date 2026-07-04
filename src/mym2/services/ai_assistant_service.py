"""可选 AI 助手服务。

AI 默认关闭、默认只读。它只能生成结构化记账草稿；真正写账必须在用户
确认后委托 LedgerService。
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date
from typing import Any

import keyring
from keyring.errors import KeyringError, NoKeyringError
from sqlalchemy.orm import Session

from mym2.db.models.account import Account
from mym2.db.models.category import Category
from mym2.db.models.transaction import Transaction
from mym2.domain.enums import TransactionType
from mym2.services.dto import CreateTransactionDTO
from mym2.services.ledger_service import LedgerService
from mym2.services.settings_service import SettingsService

KEYRING_SERVICE = 'mym2.ai'


@dataclass(frozen=True, slots=True)
class AIAssistantSettings:
    """AI 非秘密设置。"""

    enabled: bool = False
    model: str = ''
    service_url: str = ''


@dataclass(frozen=True, slots=True)
class AICredentialResult:
    """凭据保存结果。"""

    persisted: bool
    session_only: bool
    reason: str = ''


@dataclass(frozen=True, slots=True)
class AITransactionDraft:
    """AI 生成的结构化记账草稿。"""

    transaction_type: TransactionType
    transaction_date: date
    account_out_id: str
    amount_minor: int
    category_id: str | None = None
    account_in_id: str | None = None
    note: str | None = None
    estimated_impact: str = ''

    def to_dto(self) -> CreateTransactionDTO:
        """转为 LedgerService DTO。"""
        return CreateTransactionDTO(
            transaction_type=self.transaction_type,
            transaction_date=self.transaction_date,
            account_out_id=self.account_out_id,
            account_in_id=self.account_in_id,
            category_id=self.category_id,
            amount_minor=self.amount_minor,
            note=self.note,
            source='ai',
        )


class AICredentialStore:
    """AI API key 存取。

    keyring 可用时持久化到系统 keyring；不可用时仅保存在当前 Python 会话内存。
    """

    def __init__(self, service_name: str = KEYRING_SERVICE) -> None:
        self._service_name = service_name
        self._session_keys: dict[str, str] = {}

    def set_api_key(
        self,
        provider: str,
        api_key: str,
        *,
        allow_session_fallback: bool = True,
    ) -> AICredentialResult:
        """保存 API key。"""
        if not api_key:
            raise ValueError('API key 不能为空')
        try:
            keyring.set_password(self._service_name, provider, api_key)
            self._session_keys.pop(provider, None)
            return AICredentialResult(persisted=True, session_only=False)
        except (NoKeyringError, KeyringError) as exc:
            if not allow_session_fallback:
                raise
            self._session_keys[provider] = api_key
            return AICredentialResult(
                persisted=False,
                session_only=True,
                reason=exc.__class__.__name__,
            )

    def get_api_key(self, provider: str) -> str | None:
        """读取 API key。"""
        try:
            key = keyring.get_password(self._service_name, provider)
            if key:
                return key
        except (NoKeyringError, KeyringError):
            pass
        return self._session_keys.get(provider)

    def clear_session(self) -> None:
        """清除本次会话内存凭据。"""
        self._session_keys.clear()


class AIAssistantService:
    """AI 助手服务。"""

    def __init__(
        self,
        *,
        settings_service: SettingsService | None = None,
        ledger_service: LedgerService | None = None,
        credential_store: AICredentialStore | None = None,
    ) -> None:
        self._settings = settings_service or SettingsService()
        self._ledger = ledger_service or LedgerService()
        self._credentials = credential_store or AICredentialStore()

    def get_settings(self, session: Session) -> AIAssistantSettings:
        """读取 AI 设置。"""
        return AIAssistantSettings(
            enabled=self._settings.get_bool(session, 'ai_enabled', False),
            model=self._settings.get(session, 'ai_model', '') or '',
            service_url=self._settings.get(session, 'ai_service_url', '') or '',
        )

    def update_settings(
        self,
        session: Session,
        *,
        enabled: bool,
        model: str,
        service_url: str,
    ) -> None:
        """保存 AI 非秘密设置。"""
        self._settings.set_many(session, {
            'ai_enabled': 'true' if enabled else 'false',
            'ai_model': model.strip(),
            'ai_service_url': service_url.strip(),
        })

    def build_minimized_context(
        self,
        *,
        user_scope: str,
        confirmed: bool,
        accounts: list[Account] | None = None,
        categories: list[Category] | None = None,
        recent_transactions: list[Mapping[str, Any]] | None = None,
        include_notes: bool = False,
    ) -> dict[str, Any]:
        """按用户请求范围构建最小化上下文。

        不会自动读取全量数据库；调用方必须提供已经按用户范围筛选的数据。
        """
        if not confirmed:
            raise PermissionError('向 AI 提供数据前需要用户确认')
        context: dict[str, Any] = {
            'scope': user_scope,
            'accounts': [],
            'categories': [],
            'transactions': [],
        }
        for account in accounts or []:
            context['accounts'].append({
                'id': account.id,
                'type': account.type,
                'currency': account.currency,
                'balance_minor': account.current_balance_minor,
            })
        for category in categories or []:
            context['categories'].append({
                'id': category.id,
                'type': category.type,
            })
        for tx in recent_transactions or []:
            item = {
                'transaction_date': tx.get('transaction_date'),
                'type': tx.get('type'),
                'amount_minor': tx.get('amount_minor'),
                'account_out_id': tx.get('account_out_id'),
                'account_in_id': tx.get('account_in_id'),
                'category_id': tx.get('category_id'),
            }
            if include_notes:
                item['note'] = tx.get('note')
            context['transactions'].append(item)
        return context

    def create_draft(
        self,
        session: Session,
        *,
        user_text: str,
        context: dict[str, Any],
        client: Callable[[str, dict[str, Any], AIAssistantSettings], Mapping[str, Any]],
    ) -> AITransactionDraft:
        """调用外部客户端生成草稿。

        client 由上层注入，便于测试和未来接入不同提供方。
        """
        settings = self.get_settings(session)
        if not settings.enabled:
            raise PermissionError('AI 助手默认关闭，需先在设置中启用')
        response = client(user_text, context, settings)
        return self._parse_draft(response)

    def confirm_draft(
        self,
        session: Session,
        draft: AITransactionDraft,
        *,
        confirmed: bool,
    ) -> Transaction | None:
        """确认后写账；拒绝确认时不修改数据库。"""
        if not confirmed:
            return None
        return self._ledger.create_transaction(session, draft.to_dto())

    def set_api_key(
        self, provider: str, api_key: str
    ) -> AICredentialResult:
        """保存 API key 到 keyring，或 keyring 缺失时仅本次会话保存。"""
        return self._credentials.set_api_key(provider, api_key)

    def get_api_key(self, provider: str) -> str | None:
        """读取 API key。"""
        return self._credentials.get_api_key(provider)

    @staticmethod
    def _parse_draft(payload: Mapping[str, Any]) -> AITransactionDraft:
        tx_type = TransactionType(str(payload['transaction_type']))
        raw_date = payload.get('transaction_date')
        tx_date = raw_date if isinstance(raw_date, date) else date.fromisoformat(str(raw_date))
        return AITransactionDraft(
            transaction_type=tx_type,
            transaction_date=tx_date,
            account_out_id=str(payload['account_out_id']),
            account_in_id=(
                str(payload['account_in_id'])
                if payload.get('account_in_id') is not None else None
            ),
            category_id=(
                str(payload['category_id'])
                if payload.get('category_id') is not None else None
            ),
            amount_minor=int(payload['amount_minor']),
            note=(
                str(payload['note'])
                if payload.get('note') is not None else None
            ),
            estimated_impact=str(payload.get('estimated_impact') or ''),
        )
