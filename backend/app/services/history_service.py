"""Real market-history backfill and derived-quote metric refresh.

This module is the single place that writes candles and the quote metrics
derived from them (52-week range, 1M/6M/1Y returns, average volume).

Rules:
- Candles come only from the configured price provider. Nothing here invents
  prices; if the provider is unavailable the caller gets zero rows and the UI
  shows an empty state instead of a synthetic chart.
- Daily candles are stored in paise, UTC-naive timestamps (SQLite friendly).
- Minute candles are kept for a short window and purged by a scheduled job.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, Iterable, Optional, Sequence

from sqlalchemy.orm import Session

from app.models.stock import LatestQuote, PriceHistory, Stock
from app.providers import get_active_provider
from app.services.market_clock import is_replay_mode

logger = logging.getLogger(__name__)

DAILY_PERIOD = '5y'
INTRADAY_PERIOD = '5d'
INTRADAY_RETENTION_DAYS = 7


def _naive_utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _as_naive_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _candle_values(candle: dict) -> tuple:
    return (
        _as_naive_utc(candle['ts']),
        int(candle['open']),
        int(candle['high']),
        int(candle['low']),
        int(candle['close']),
        int(candle.get('volume') or 0),
    )


def replace_history(
    db: Session,
    stock_id: int,
    interval: str,
    candles: Iterable[dict],
    commit: bool = True,
) -> int:
    """Delete existing candles for one stock/interval and insert fresh rows.

    Used when repairing seeded/synthetic history: replacing the whole series is
    safer than merging fake rows with real ones.
    """
    db.query(PriceHistory).filter(
        PriceHistory.stock_id == stock_id,
        PriceHistory.interval == interval,
    ).delete(synchronize_session=False)

    count = 0
    for candle in candles:
        try:
            ts, o, h, l, c, v = _candle_values(candle)
        except (KeyError, TypeError, ValueError):
            continue
        db.add(PriceHistory(
            stock_id=stock_id,
            interval=interval,
            ts=ts,
            open=o,
            high=h,
            low=l,
            close=c,
            volume=v,
        ))
        count += 1

    if commit:
        db.commit()
    return count


def upsert_history(
    db: Session,
    stock_id: int,
    interval: str,
    candles: Iterable[dict],
    commit: bool = True,
) -> int:
    """Insert new candles and update the values of candles already stored."""
    existing = {
        _as_naive_utc(row.ts): row
        for row in db.query(PriceHistory).filter(
            PriceHistory.stock_id == stock_id,
            PriceHistory.interval == interval,
        ).all()
    }

    touched = 0
    for candle in candles:
        try:
            ts, o, h, l, c, v = _candle_values(candle)
        except (KeyError, TypeError, ValueError):
            continue
        row = existing.get(ts)
        if row is None:
            db.add(PriceHistory(
                stock_id=stock_id,
                interval=interval,
                ts=ts,
                open=o,
                high=h,
                low=l,
                close=c,
                volume=v,
            ))
        else:
            row.open, row.high, row.low, row.close, row.volume = o, h, l, c, v
        touched += 1

    if commit:
        db.commit()
    return touched


def _close_at_or_before(candles: Sequence[PriceHistory], cutoff: datetime) -> Optional[int]:
    found: Optional[int] = None
    for candle in candles:
        if _as_naive_utc(candle.ts) <= cutoff:
            found = candle.close
        else:
            break
    return found


def recompute_quote_metrics(db: Session, stock: Stock, commit: bool = True) -> bool:
    """Recompute 52W range, trailing returns and 20-day average volume."""
    candles = db.query(PriceHistory).filter(
        PriceHistory.stock_id == stock.id,
        PriceHistory.interval == '1d',
    ).order_by(PriceHistory.ts.asc()).all()

    quote = stock.quote or db.query(LatestQuote).filter(
        LatestQuote.stock_id == stock.id
    ).first()
    if not candles or not quote:
        return False

    latest = candles[-1]
    latest_close = quote.price or latest.close
    anchor = _as_naive_utc(latest.ts)

    year_cutoff = anchor - timedelta(days=365)
    year_candles = [c for c in candles if _as_naive_utc(c.ts) >= year_cutoff]
    if not year_candles:
        year_candles = list(candles[-252:])

    quote.week52_high = max(c.high for c in year_candles)
    quote.week52_low = min(c.low for c in year_candles)

    for days, attr in ((30, 'return_1m_pct'), (182, 'return_6m_pct'), (365, 'return_1y_pct')):
        base = _close_at_or_before(candles, anchor - timedelta(days=days))
        if base and base > 0:
            setattr(quote, attr, round((latest_close / base - 1.0) * 100.0, 2))
        else:
            setattr(quote, attr, None)

    recent_volumes = [c.volume for c in candles[-20:] if c.volume]
    quote.avg_volume_20d = int(sum(recent_volumes) / len(recent_volumes)) if recent_volumes else None

    if commit:
        db.commit()
    return True


def backfill_daily_history(
    db: Session,
    stock: Stock,
    period: str = DAILY_PERIOD,
    replace: bool = True,
) -> int:
    """Fetch daily candles for one stock and refresh its derived metrics."""
    provider = get_active_provider(is_replay_mode(db))
    candles = provider.get_history(stock.yf_symbol, interval='1d', period=period) or []
    if not candles:
        return 0

    if replace:
        count = replace_history(db, stock.id, '1d', candles, commit=False)
    else:
        count = upsert_history(db, stock.id, '1d', candles, commit=False)

    db.flush()
    recompute_quote_metrics(db, stock, commit=False)
    db.commit()
    return count


def backfill_intraday_history(
    db: Session,
    stock: Stock,
    period: str = INTRADAY_PERIOD,
) -> int:
    """Fetch recent minute candles for the 1D chart."""
    provider = get_active_provider(is_replay_mode(db))
    candles = provider.get_history(stock.yf_symbol, interval='1m', period=period) or []
    if not candles:
        return 0
    count = replace_history(db, stock.id, '1m', candles, commit=False)
    db.commit()
    return count


def refresh_daily_history(
    db: Session,
    symbols: Optional[Iterable[str]] = None,
    period: str = DAILY_PERIOD,
) -> Dict[str, int]:
    """Refresh daily candles + metrics for active stocks.

    Runs once a day and upserts (never deletes) so historical rows survive.
    """
    query = db.query(Stock).filter(Stock.is_active == True)  # noqa: E712
    if symbols:
        wanted = [s.upper() for s in symbols]
        query = query.filter(Stock.symbol.in_(wanted))

    stats = {'stocks': 0, 'updated': 0, 'failed': 0}
    for stock in query.all():
        stats['stocks'] += 1
        try:
            count = backfill_daily_history(db, stock, period=period, replace=False)
            if count:
                stats['updated'] += 1
        except Exception as exc:  # keep the job alive for the next symbol
            db.rollback()
            stats['failed'] += 1
            logger.warning('Daily history refresh failed for %s: %s', stock.symbol, exc)

    logger.info(
        'Daily history refresh: %s stocks, %s updated, %s failed',
        stats['stocks'], stats['updated'], stats['failed'],
    )
    return stats


def refresh_company_info(db: Session) -> Dict[str, int]:
    """Refresh company metadata and 52-week ranges from the provider."""
    provider = get_active_provider(is_replay_mode(db))
    stats = {'stocks': 0, 'updated': 0, 'failed': 0}

    for stock in db.query(Stock).filter(Stock.is_active == True).all():  # noqa: E712
        stats['stocks'] += 1
        try:
            info = provider.get_company_info(stock.yf_symbol) or {}
            if not info:
                continue

            if info.get('name'):
                stock.company_name = info['name']
            if info.get('sector'):
                stock.sector = info['sector']
            if info.get('industry'):
                stock.industry = info['industry']
            if info.get('market_cap'):
                stock.market_cap = info['market_cap']
            if info.get('pe_ratio') is not None:
                stock.pe_ratio = info['pe_ratio']
            if info.get('dividend_yield') is not None:
                stock.dividend_yield = info['dividend_yield']
            if info.get('description'):
                stock.description = info['description']

            quote = stock.quote
            if quote:
                if info.get('week52_high'):
                    quote.week52_high = info['week52_high']
                if info.get('week52_low'):
                    quote.week52_low = info['week52_low']

            db.commit()
            stats['updated'] += 1
        except Exception as exc:
            db.rollback()
            stats['failed'] += 1
            logger.warning('Company info refresh failed for %s: %s', stock.symbol, exc)

    logger.info(
        'Company info refresh: %s stocks, %s updated, %s failed',
        stats['stocks'], stats['updated'], stats['failed'],
    )
    return stats


def purge_old_minute_candles(db: Session, days: int = INTRADAY_RETENTION_DAYS) -> int:
    cutoff = _naive_utc_now() - timedelta(days=days)
    deleted = db.query(PriceHistory).filter(
        PriceHistory.interval == '1m',
        PriceHistory.ts < cutoff,
    ).delete(synchronize_session=False)
    db.commit()
    if deleted:
        logger.info('Purged %s minute candles older than %s days', deleted, days)
    return deleted
