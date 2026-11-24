"""Simple backtesting engine over stored daily candles."""
import math
from typing import List, Dict, Any
from sqlalchemy.orm import Session
from app.models.stock import Stock, PriceHistory


def _sma(vals: List[float], n: int) -> List[float]:
    out = [float('nan')] * len(vals)
    for i in range(n - 1, len(vals)):
        out[i] = sum(vals[i - n + 1:i + 1]) / n
    return out


def _rsi(vals: List[float], n: int = 14) -> List[float]:
    out = [float('nan')] * len(vals)
    if len(vals) < n + 1:
        return out
    gains = [0.0] * len(vals)
    losses = [0.0] * len(vals)
    for i in range(1, len(vals)):
        d = vals[i] - vals[i - 1]
        gains[i] = d if d > 0 else 0.0
        losses[i] = -d if d < 0 else 0.0
    avg_gain = sum(gains[1:n + 1]) / n
    avg_loss = sum(losses[1:n + 1]) / n
    for i in range(n, len(vals)):
        if i > n:
            avg_gain = (avg_gain * (n - 1) + gains[i]) / n
            avg_loss = (avg_loss * (n - 1) + losses[i]) / n
        rs = avg_gain / avg_loss if avg_loss else float('inf')
        out[i] = 100 - (100 / (1 + rs))
    return out


def run_backtest(db: Session, symbol: str, strategy: str, params: Dict[str, Any], period_days: int = 252) -> Dict[str, Any]:
    stock = db.query(Stock).filter(Stock.symbol == symbol.upper()).first()
    if not stock:
        return {'error': f'Stock {symbol} not found. Add it first.'}
    candles = db.query(PriceHistory).filter(
        PriceHistory.stock_id == stock.id,
        PriceHistory.interval == '1d',
    ).order_by(PriceHistory.ts.asc()).all()

    # Backfill more history on demand for richer backtests
    if len(candles) < 100:
        try:
            from app.providers import get_active_provider
            from app.services.market_clock import is_replay_mode
            provider = get_active_provider(is_replay_mode(db))
            hist = provider.get_history(stock.yf_symbol, interval='1d', period='2y') or []
            existing_ts = {c.ts for c in candles}
            for c in hist:
                if c['ts'] in existing_ts:
                    continue
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
            db.commit()
            candles = db.query(PriceHistory).filter(
                PriceHistory.stock_id == stock.id,
                PriceHistory.interval == '1d',
            ).order_by(PriceHistory.ts.asc()).all()
        except Exception:
            pass

    if len(candles) < 30:
        return {'error': 'Not enough historical data. Need at least 30 daily candles.'}

    closes = [c.close / 100.0 for c in candles]
    dates = [c.ts.isoformat() if hasattr(c.ts, 'isoformat') else str(c.ts) for c in candles]

    # trim to period_days
    if period_days and len(closes) > period_days:
        closes = closes[-period_days:]
        dates = dates[-period_days:]
        candles = candles[-period_days:]

    strategy = (strategy or 'buy_hold').lower()
    n = len(closes)
    fast = int(params.get('fast', 10))
    slow = int(params.get('slow', 30))
    rsi_buy = float(params.get('rsi_buy', 30))
    rsi_sell = float(params.get('rsi_sell', 70))

    # signals: 1 buy, -1 sell, 0 hold
    signals = [0] * n
    if strategy == 'sma_crossover':
        f = _sma(closes, fast)
        s = _sma(closes, slow)
        for i in range(1, n):
            if math.isnan(f[i]) or math.isnan(s[i]) or math.isnan(f[i - 1]) or math.isnan(s[i - 1]):
                continue
            if f[i - 1] <= s[i - 1] and f[i] > s[i]:
                signals[i] = 1
            elif f[i - 1] >= s[i - 1] and f[i] < s[i]:
                signals[i] = -1
    elif strategy == 'rsi':
        r = _rsi(closes, 14)
        for i in range(1, n):
            if math.isnan(r[i]):
                continue
            if r[i] < rsi_buy:
                signals[i] = 1
            elif r[i] > rsi_sell:
                signals[i] = -1
    elif strategy == 'buy_hold':
        signals[0] = 1
        signals[-1] = -1
    else:
        return {'error': f'Unknown strategy {strategy}'}

    # simulate
    cash = 100000.0
    qty = 0
    equity = []
    trades = []
    entry_price = None
    for i in range(n):
        price = closes[i]
        if signals[i] == 1 and qty == 0:
            qty = cash / price
            cash = 0.0
            entry_price = price
            trades.append({'type': 'BUY', 'date': dates[i], 'price': round(price, 2), 'qty': round(qty, 4)})
        elif signals[i] == -1 and qty > 0:
            cash = qty * price
            pnl = (price - entry_price) * qty if entry_price else 0.0
            trades.append({'type': 'SELL', 'date': dates[i], 'price': round(price, 2), 'qty': round(qty, 4), 'pnl': round(pnl, 2)})
            qty = 0
            entry_price = None
        equity.append(cash + qty * price)

    # close open position at end
    if qty > 0:
        cash = qty * closes[-1]
        pnl = (closes[-1] - entry_price) * qty if entry_price else 0.0
        trades.append({'type': 'SELL', 'date': dates[-1], 'price': round(closes[-1], 2), 'qty': round(qty, 4), 'pnl': round(pnl, 2)})
        qty = 0
        equity[-1] = cash

    # metrics
    initial = 100000.0
    final = equity[-1] if equity else initial
    total_return = (final / initial - 1.0) * 100.0
    years = n / 252.0
    cagr = ((final / initial) ** (1.0 / years) - 1.0) * 100.0 if years > 0 and final > 0 else 0.0

    daily_returns = [equity[i] / equity[i - 1] - 1.0 for i in range(1, len(equity)) if equity[i - 1]]
    mean_r = sum(daily_returns) / len(daily_returns) if daily_returns else 0.0
    std_r = (sum((r - mean_r) ** 2 for r in daily_returns) / len(daily_returns)) ** 0.5 if daily_returns else 0.0
    sharpe = (mean_r / std_r * (252 ** 0.5)) if std_r else 0.0

    peak = equity[0] if equity else 0
    max_dd = 0.0
    for v in equity:
        if v > peak:
            peak = v
        dd = (peak - v) / peak if peak else 0.0
        if dd > max_dd:
            max_dd = dd
    max_dd_pct = max_dd * 100.0

    sell_trades = [t for t in trades if t['type'] == 'SELL']
    wins = [t for t in sell_trades if t.get('pnl', 0) > 0]
    win_rate = (len(wins) / len(sell_trades) * 100.0) if sell_trades else 0.0

    return {
        'symbol': stock.symbol,
        'strategy': strategy,
        'params': params,
        'period_days': n,
        'initial_capital': initial,
        'final_equity': round(final, 2),
        'total_return_pct': round(total_return, 2),
        'cagr_pct': round(cagr, 2),
        'sharpe': round(sharpe, 3),
        'max_drawdown_pct': round(max_dd_pct, 2),
        'trade_count': len(sell_trades),
        'win_rate_pct': round(win_rate, 2),
        'equity_curve': [{'date': dates[i], 'value': round(equity[i], 2)} for i in range(len(equity))],
        'trades': trades,
    }
