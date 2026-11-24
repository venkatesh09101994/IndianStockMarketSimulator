import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import or_, func
from app.api.deps import get_db, get_optional_current_user, get_current_user
from app.models.user import User
from app.models.stock import Stock, LatestQuote, PriceHistory
from app.models.watchlist import WatchlistItem
from app.schemas.stock import (
    StockBrief, StockDetail, LatestQuoteOut, CandleOut, StockCompareOut,
    MarketStatusOut, TickerItem
)
from app.services.market_clock import (
    IST, get_ist_now, get_market_status_details, is_market_open
)
from app.services.history_service import backfill_daily_history, backfill_intraday_history
from app.services.stock_onboard import search_online, add_stock

logger = logging.getLogger(__name__)

router = APIRouter(tags=['Stocks'])

# On-demand backfill is a best-effort repair path. If the provider is down we
# retry at most once every ten minutes per stock/interval instead of hammering
# it on every chart request.
_BACKFILL_COOLDOWN_SECONDS = 600
_last_backfill_attempt: Dict[Tuple[int, str], datetime] = {}


def _should_backfill(stock_id: int, interval: str) -> bool:
    key = (stock_id, interval)
    now = datetime.now(timezone.utc)
    last = _last_backfill_attempt.get(key)
    if last is not None and (now - last).total_seconds() < _BACKFILL_COOLDOWN_SECONDS:
        return False
    _last_backfill_attempt[key] = now
    return True

def _as_utc(dt: Optional[datetime]) -> Optional[datetime]:
    """SQLite returns naive datetimes; treat them as UTC so clients can parse them reliably."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)

def quote_to_out(q: LatestQuote) -> LatestQuoteOut:
    return LatestQuoteOut(
        price=round(q.price / 100.0, 2),
        prev_close=round(q.prev_close / 100.0, 2),
        open=round(q.open / 100.0, 2),
        day_high=round(q.day_high / 100.0, 2),
        day_low=round(q.day_low / 100.0, 2),
        volume=q.volume,
        day_change=round(q.day_change / 100.0, 2),
        day_change_pct=round(q.day_change_pct, 2),
        week52_high=round(q.week52_high / 100.0, 2) if q.week52_high else None,
        week52_low=round(q.week52_low / 100.0, 2) if q.week52_low else None,
        return_1m_pct=round(q.return_1m_pct, 2) if q.return_1m_pct is not None else None,
        return_6m_pct=round(q.return_6m_pct, 2) if q.return_6m_pct is not None else None,
        return_1y_pct=round(q.return_1y_pct, 2) if q.return_1y_pct is not None else None,
        avg_volume_20d=q.avg_volume_20d,
        updated_at=_as_utc(q.updated_at)
    )

@router.get('/stocks', response_model=List[StockBrief])
def get_stocks(
    search: Optional[str] = None,
    sector: Optional[str] = None,
    sort: Optional[str] = 'symbol',
    page: int = 1,
    limit: Optional[int] = None,
    db: Session = Depends(get_db),
    user: Optional[User] = Depends(get_optional_current_user)
):
    query = db.query(Stock).options(joinedload(Stock.quote)).filter(Stock.is_active == True)

    if search:
        search_fmt = f'%{search}%'
        query = query.filter(or_(Stock.symbol.ilike(search_fmt), Stock.company_name.ilike(search_fmt)))

    if sector and sector != 'All':
        query = query.filter(Stock.sector == sector)

    # Get user watchlist IDs
    watchlist_stock_ids = set()
    if user:
        items = db.query(WatchlistItem.stock_id).filter(WatchlistItem.user_id == user.id).all()
        watchlist_stock_ids = {i[0] for i in items}

    stocks = query.all()

    # In-memory sorting for properties like day_change_pct
    if sort == 'change':
        stocks = sorted(stocks, key=lambda s: s.quote.day_change_pct if s.quote else 0.0, reverse=True)
    elif sort == 'price':
        stocks = sorted(stocks, key=lambda s: s.quote.price if s.quote else 0, reverse=True)
    elif sort == 'volume':
        stocks = sorted(stocks, key=lambda s: s.quote.volume if s.quote else 0, reverse=True)
    elif sort == 'market_cap':
        stocks = sorted(stocks, key=lambda s: s.market_cap or 0, reverse=True)

    # Optional pagination. The header search asks for a handful of results,
    # while the screener omits `limit` and expects the full universe.
    if limit and limit > 0:
        start = max(0, (max(page, 1) - 1) * limit)
        stocks = stocks[start:start + limit]

    results = []
    for s in stocks:
        q_out = quote_to_out(s.quote) if s.quote else None
        mcap_cr = round(s.market_cap / 10000000.0, 2) if s.market_cap else None
        results.append(StockBrief(
            id=s.id,
            symbol=s.symbol,
            yf_symbol=s.yf_symbol,
            exchange=s.exchange,
            company_name=s.company_name,
            sector=s.sector,
            logo_url=s.logo_url,
            market_cap=mcap_cr,
            pe_ratio=s.pe_ratio,
            dividend_yield=s.dividend_yield,
            quote=q_out,
            in_watchlist=s.id in watchlist_stock_ids
        ))
    return results

@router.get('/stocks/compare', response_model=List[StockCompareOut])
def compare_stocks(symbols: str = Query('RELIANCE,TCS,INFY,HDFCBANK'), db: Session = Depends(get_db)):
    sym_list = [s.strip().upper() for s in symbols.split(',') if s.strip()]
    stocks = db.query(Stock).filter(Stock.symbol.in_(sym_list)).all()
    results = []
    for s in stocks:
        q = s.quote
        results.append(StockCompareOut(
            symbol=s.symbol,
            company_name=s.company_name,
            sector=s.sector,
            price=round(q.price / 100.0, 2) if q else 0.0,
            day_change_pct=round(q.day_change_pct, 2) if q else 0.0,
            pe_ratio=s.pe_ratio,
            market_cap=round(s.market_cap / 10000000.0, 2) if s.market_cap else None,
            week52_high=round(q.week52_high / 100.0, 2) if q and q.week52_high else None,
            week52_low=round(q.week52_low / 100.0, 2) if q and q.week52_low else None
        ))
    return results


@router.get('/stocks/search/online')
def search_stocks_online(
    q: str = Query(''),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    results = search_online(q)
    # annotate already in DB
    existing = {s.yf_symbol for s in db.query(Stock.yf_symbol).all()}
    for r in results:
        r['in_db'] = r['yf_symbol'] in existing
    return results

@router.post('/stocks/add')
def add_stock_endpoint(
    payload: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    symbol_input = (payload or {}).get('symbol', '').strip()
    if not symbol_input:
        raise HTTPException(status_code=400, detail='symbol required')
    stock = add_stock(db, symbol_input)
    if not stock:
        raise HTTPException(status_code=400, detail='Could not add stock')
    return {'symbol': stock.symbol, 'yf_symbol': stock.yf_symbol, 'company_name': stock.company_name, 'sector': stock.sector}

@router.get('/stocks/{symbol}', response_model=StockDetail)
def get_stock_detail(
    symbol: str,
    db: Session = Depends(get_db),
    user: Optional[User] = Depends(get_optional_current_user)
):
    s = db.query(Stock).filter(Stock.symbol == symbol.upper()).first()
    if not s:
        raise HTTPException(status_code=404, detail='Stock not found')

    in_watch = False
    if user:
        in_watch = db.query(WatchlistItem).filter(
            WatchlistItem.user_id == user.id,
            WatchlistItem.stock_id == s.id
        ).first() is not None

    q_out = quote_to_out(s.quote) if s.quote else None
    mcap_cr = round(s.market_cap / 10000000.0, 2) if s.market_cap else None

    return StockDetail(
        id=s.id,
        symbol=s.symbol,
        yf_symbol=s.yf_symbol,
        exchange=s.exchange,
        company_name=s.company_name,
        sector=s.sector,
        industry=s.industry,
        description=s.description,
        logo_url=s.logo_url,
        market_cap=mcap_cr,
        pe_ratio=s.pe_ratio,
        dividend_yield=s.dividend_yield,
        quote=q_out,
        in_watchlist=in_watch
    )

def _candle_out(c: PriceHistory) -> CandleOut:
    return CandleOut(
        ts=_as_utc(c.ts),
        open=round(c.open / 100.0, 2),
        high=round(c.high / 100.0, 2),
        low=round(c.low / 100.0, 2),
        close=round(c.close / 100.0, 2),
        volume=c.volume,
    )


def _load_daily_candles(db: Session, stock: Stock) -> List[PriceHistory]:
    return db.query(PriceHistory).filter(
        PriceHistory.stock_id == stock.id,
        PriceHistory.interval == '1d',
    ).order_by(PriceHistory.ts.asc()).all()


def _load_intraday_candles(db: Session, stock: Stock) -> List[PriceHistory]:
    return db.query(PriceHistory).filter(
        PriceHistory.stock_id == stock.id,
        PriceHistory.interval == '1m',
    ).order_by(PriceHistory.ts.asc()).all()


def _looks_synthetic(candles: List[PriceHistory]) -> bool:
    """Seeded demo candles include weekend dates; real NSE daily candles never do."""
    return any(_as_utc(c.ts).astimezone(IST).weekday() >= 5 for c in candles)


def _intraday_history(db: Session, stock: Stock) -> List[CandleOut]:
    candles = _load_intraday_candles(db, stock)

    # During a live session the newest stored minute bar goes stale quickly, so
    # refresh it (rate-limited by the backfill cooldown). When the market is
    # closed we keep the last session unless there is no data at all.
    stale = not candles
    if candles:
        latest_ts = max(_as_utc(c.ts) for c in candles)
        stale = is_market_open(db) and (
            datetime.now(timezone.utc) - latest_ts
        ) > timedelta(minutes=5)

    if stale and _should_backfill(stock.id, '1m'):
        try:
            backfill_intraday_history(db, stock)
        except Exception as exc:
            db.rollback()
            logger.warning('Intraday backfill failed for %s: %s', stock.symbol, exc)
        candles = _load_intraday_candles(db, stock)

    if not candles:
        return []

    latest_day = max(_as_utc(c.ts).astimezone(IST).date() for c in candles)
    todays = [
        c for c in candles
        if _as_utc(c.ts).astimezone(IST).date() == latest_day
    ]
    return [_candle_out(c) for c in todays]


_DAILY_LOOKBACK_DAYS = {
    '7D': 7,
    '1W': 7,
    '1M': 30,
    '3M': 90,
    '6M': 182,
    '1Y': 365,
    '5Y': 1825,
}

# Minimum number of stored candles before we trust the series for a timeframe.
_MIN_CANDLES = {
    '7D': 5,
    '1W': 5,
    '1M': 20,
    '3M': 55,
    '6M': 100,
    '1Y': 180,
    'YTD': 20,
    '5Y': 180,
    'ALL': 180,
}


def _daily_history(db: Session, stock: Stock, timeframe: str) -> List[CandleOut]:
    tf = (timeframe or '1M').upper()
    candles = _load_daily_candles(db, stock)

    needs_repair = _looks_synthetic(candles) or len(candles) < _MIN_CANDLES.get(tf, 20)
    if needs_repair and _should_backfill(stock.id, '1d'):
        period = '5y' if tf in ('5Y', 'ALL') else '2y'
        try:
            backfill_daily_history(db, stock, period=period, replace=True)
        except Exception as exc:
            db.rollback()
            logger.warning('Daily backfill failed for %s: %s', stock.symbol, exc)
        candles = _load_daily_candles(db, stock)

    if not candles:
        return []

    now_ist = get_ist_now()
    if tf == 'YTD':
        cutoff = datetime(now_ist.year, 1, 1, tzinfo=IST)
    elif tf in _DAILY_LOOKBACK_DAYS:
        cutoff = now_ist - timedelta(days=_DAILY_LOOKBACK_DAYS[tf])
    else:
        cutoff = None

    if cutoff is not None:
        candles = [c for c in candles if _as_utc(c.ts) >= cutoff]

    # Keep payloads sane for ALL/5Y while still showing real history.
    if tf in ('5Y', 'ALL') and len(candles) > 1500:
        candles = candles[-1500:]

    return [_candle_out(c) for c in candles]


@router.get('/stocks/{symbol}/history', response_model=List[CandleOut])
def get_stock_history(
    symbol: str,
    interval: str = '1d',
    timeframe: str = Query('1M', alias='range'),
    db: Session = Depends(get_db)
):
    """Return real stored candles only.

    There is intentionally no synthetic fallback: a missing series returns an
    empty list so the UI can show an honest empty state.
    """
    s = db.query(Stock).filter(Stock.symbol == symbol.upper()).first()
    if not s:
        raise HTTPException(status_code=404, detail='Stock not found')

    if interval == '1m' or (timeframe or '').upper() == '1D':
        return _intraday_history(db, s)
    return _daily_history(db, s, timeframe)

@router.post('/market/refresh')
def refresh_market_data(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Force a quote refresh, e.g. when the desktop window is reopened."""
    from app.jobs.scheduler import job_refresh_quotes
    job_refresh_quotes(db)
    latest = (
        db.query(func.max(LatestQuote.updated_at))
        .join(Stock, Stock.id == LatestQuote.stock_id)
        .filter(Stock.is_active == True)
        .scalar()
    )
    return {'status': 'refreshed', 'last_updated': _as_utc(latest)}


@router.get('/market/status', response_model=MarketStatusOut)
def get_market_status(db: Session = Depends(get_db)):
    details = get_market_status_details(db)

    # When were stock prices last refreshed? Use the newest quote timestamp
    # across active stocks so the UI can show a single, trustworthy timestamp.
    latest = (
        db.query(func.max(LatestQuote.updated_at))
        .join(Stock, Stock.id == LatestQuote.stock_id)
        .filter(Stock.is_active == True)
        .scalar()
    )
    last_updated = _as_utc(latest)
    age_seconds = None
    if last_updated is not None:
        age_seconds = max(0, int((datetime.now(timezone.utc) - last_updated).total_seconds()))

    details['last_updated'] = last_updated
    details['data_age_seconds'] = age_seconds
    return MarketStatusOut(**details)

@router.get('/market/ticker', response_model=List[TickerItem])
def get_market_ticker(db: Session = Depends(get_db)):
    stocks = (
        db.query(Stock)
        .options(joinedload(Stock.quote))
        .filter(Stock.is_active == True)
        .limit(12)
        .all()
    )
    items = []
    for s in stocks:
        q = s.quote
        if q:
            items.append(TickerItem(
                symbol=s.symbol,
                name=s.company_name,
                price=round(q.price / 100.0, 2),
                day_change=round(q.day_change / 100.0, 2),
                day_change_pct=round(q.day_change_pct, 2)
            ))
    return items
