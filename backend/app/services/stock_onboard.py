"""Dynamically onboard a stock that is not in the local seed list."""
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any
from sqlalchemy.orm import Session
from app.models.stock import Stock, LatestQuote, PriceHistory
from app.providers import get_active_provider
from app.services.market_clock import is_replay_mode

logger = logging.getLogger(__name__)


def _normalize(symbol_input: str):
    s = (symbol_input or '').strip().upper()
    if not s:
        return None
    if s.endswith('.NS'):
        return s[:-3], 'NSE', s
    if s.endswith('.BO'):
        return s[:-3], 'BSE', s
    # default to NSE
    return s, 'NSE', s + '.NS'


def search_online(query: str) -> list:
    import requests
    q = (query or '').strip()
    if not q:
        return []
    try:
        url = 'https://query2.finance.yahoo.com/v1/finance/search'
        r = requests.get(url, params={'q': q, 'quotesCount': 15, 'newsCount': 0, 'enableFuzzyQuery': False}, timeout=10, headers={'User-Agent': 'Mozilla/5.0'})
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        logger.warning(f'online search failed: {e}')
        return []
    out = []
    for item in data.get('quotes', []) or []:
        sym = item.get('symbol')
        if not sym:
            continue
        # keep Indian exchanges
        exch = item.get('exchange') or ''
        if not (sym.endswith('.NS') or sym.endswith('.BO') or exch in ('NSE', 'BSE', 'NSI', 'BSE')):
            continue
        out.append({
            'symbol': sym.replace('.NS', '').replace('.BO', ''),
            'name': item.get('shortname') or item.get('longname') or sym,
            'exchange': 'NSE' if sym.endswith('.NS') else ('BSE' if sym.endswith('.BO') else exch),
            'yf_symbol': sym,
            'sector': item.get('sector') or item.get('industry') or '',
        })
    # dedupe
    seen = set()
    uniq = []
    for o in out:
        if o['yf_symbol'] in seen:
            continue
        seen.add(o['yf_symbol'])
        uniq.append(o)
    return uniq


def add_stock(db: Session, symbol_input: str) -> Optional[Stock]:
    symbol, exchange, yf_symbol = _normalize(symbol_input)
    if not symbol:
        return None

    existing = db.query(Stock).filter((Stock.symbol == symbol) | (Stock.yf_symbol == yf_symbol)).first()
    if existing:
        return existing

    provider = get_active_provider(is_replay_mode(db))

    stock = Stock(
        symbol=symbol,
        yf_symbol=yf_symbol,
        exchange=exchange,
        company_name=symbol,
        sector='Unknown',
        is_active=True,
    )
    db.add(stock)
    db.flush()

    info = {}
    # company info
    try:
        info = provider.get_company_info(yf_symbol) or {}
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
    except Exception as e:
        logger.warning(f'company info fetch failed for {yf_symbol}: {e}')

    # quote
    try:
        quotes = provider.get_quotes([yf_symbol]) or {}
        qd = quotes.get(yf_symbol)
        if qd:
            q = LatestQuote(stock_id=stock.id)
            q.price = qd['price']
            q.prev_close = qd['prev_close']
            q.open = qd['open']
            q.day_high = qd['day_high']
            q.day_low = qd['day_low']
            q.volume = qd['volume']
            q.day_change = qd['day_change']
            q.day_change_pct = qd['day_change_pct']
            q.week52_high = qd.get('week52_high') or info.get('week52_high')
            q.week52_low = qd.get('week52_low') or info.get('week52_low')
            q.updated_at = datetime.now(timezone.utc)
            db.add(q)
    except Exception as e:
        logger.warning(f'quote fetch failed for {yf_symbol}: {e}')

    # history (1d, ~2y)
    try:
        candles = provider.get_history(yf_symbol, interval='1d', period='2y') or []
        for c in candles:
            db.add(PriceHistory(
                stock_id=stock.id,
                interval='1d',
                ts=c['ts'],
                open=c['open'],
                high=c['high'],
                low=c['low'],
                close=c['close'],
                volume=c['volume'],
            ))
    except Exception as e:
        logger.warning(f'history fetch failed for {yf_symbol}: {e}')

    db.commit()
    db.refresh(stock)
    return stock
