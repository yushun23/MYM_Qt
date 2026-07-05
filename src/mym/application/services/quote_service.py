"""QuoteService – security price data, offline cache, bulk sync (P25)."""

import json
import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session

from mym.domain.entities.investment import QuoteSnapshot, Security
from mym.infrastructure.repositories.investment_repo import InvestmentRepository

logger = logging.getLogger(__name__)


@dataclass
class QuoteData:
    symbol: str
    date: date
    open: Decimal | None = None
    high: Decimal | None = None
    low: Decimal | None = None
    close: Decimal | None = None
    volume: int | None = None

    def is_valid(self) -> bool:
        return self.close is not None and self.close > 0


class QuoteService:
    """Manages security price quotes with offline caching."""

    _CACHE_TTL_DAYS = 1

    def __init__(self, session: Session, cache_dir: Path | None = None) -> None:
        self._session = session
        self._repo = InvestmentRepository(session)
        self._cache_dir = cache_dir

    def get_latest_quote(self, security_id: int) -> QuoteSnapshot | None:
        return self._repo.get_latest_quote(security_id)

    def get_latest_price(self, security_id: int) -> Decimal:
        quote = self.get_latest_quote(security_id)
        return quote.close_price if quote else Decimal("0")

    def save_quote(
        self,
        security_id: int,
        quote_date: date,
        close_price: Decimal,
        open_price: Decimal | None = None,
        high_price: Decimal | None = None,
        low_price: Decimal | None = None,
        volume: int | None = None,
        source: str = "manual",
    ) -> QuoteSnapshot:
        """Save a quote snapshot."""
        quote = QuoteSnapshot(
            security_id=security_id,
            quote_date=quote_date,
            close_price=close_price,
            open_price=open_price,
            high_price=high_price,
            low_price=low_price,
            volume=volume,
            source=source,
        )
        self._repo.add_quote(quote)
        return quote

    def save_bulk_quotes(
        self, quotes: list[QuoteData]
    ) -> int:
        """Save multiple quotes in bulk. Returns count saved."""
        count = 0
        for qd in quotes:
            if not qd.is_valid():
                continue
            sec = self._repo.find_security_by_symbol(qd.symbol)
            if not sec:
                logger.warning("Unknown security: %s", qd.symbol)
                continue
            self.save_quote(
                security_id=sec.id,
                quote_date=qd.date,
                close_price=qd.close,  # type: ignore[arg-type]
                open_price=qd.open,
                high_price=qd.high,
                low_price=qd.low,
                volume=qd.volume,
                source="bulk_import",
            )
            count += 1
        return count

    def is_stale(self, security_id: int) -> bool:
        """Check if latest quote is older than TTL."""
        quote = self.get_latest_quote(security_id)
        if not quote:
            return True
        age = (date.today() - quote.quote_date).days
        return age > self._CACHE_TTL_DAYS

    def get_price_history(
        self, security_id: int, days: int = 30
    ) -> list[dict]:
        """Get recent price history for charting."""
        from sqlalchemy import select

        cutoff = date.today() - timedelta(days=days)
        stmt = (
            select(QuoteSnapshot)
            .where(
                QuoteSnapshot.security_id == security_id,
                QuoteSnapshot.quote_date >= cutoff,
            )
            .order_by(QuoteSnapshot.quote_date)
        )
        quotes = self._session.execute(stmt).scalars().all()
        return [
            {
                "date": str(q.quote_date),
                "close": str(q.close_price),
                "open": str(q.open_price) if q.open_price else None,
                "high": str(q.high_price) if q.high_price else None,
                "low": str(q.low_price) if q.low_price else None,
                "volume": q.volume,
            }
            for q in quotes
        ]
