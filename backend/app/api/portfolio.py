from typing import List
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
import csv, io
from app.api.deps import get_db, get_current_user
from app.models.user import User
from app.models.trade import Trade
from app.models.wallet import WalletTransaction
from app.models.snapshot import PortfolioSnapshot
from app.providers import price_provider
from app.services.market_clock import get_ist_now
from app.schemas.order import TradeOut
from app.schemas.portfolio import (
    PortfolioSummaryOut, HoldingOut, PositionOut, SectorAllocationOut,
    WalletTransactionOut, SnapshotOut
)
from app.services.portfolio_service import (
    get_portfolio_summary, get_holdings_list, get_positions_list, get_sector_allocation
)
from app.utils.time import to_utc

router = APIRouter(prefix='/portfolio', tags=['Portfolio'])

@router.get('/summary', response_model=PortfolioSummaryOut)
def summary(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return get_portfolio_summary(db, current_user.id)

@router.get('/holdings', response_model=List[HoldingOut])
def holdings(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return get_holdings_list(db, current_user.id)

@router.get('/positions', response_model=List[PositionOut])
def positions(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return get_positions_list(db, current_user.id)

@router.get('/trades', response_model=List[TradeOut])
def trades(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    user_trades = db.query(Trade).filter(Trade.user_id == current_user.id).order_by(Trade.id.desc()).all()
    return [
        TradeOut(
            id=t.id,
            order_id=t.order_id,
            stock_symbol=t.stock.symbol,
            company_name=t.stock.company_name,
            side=t.side,
            product_type=t.product_type,
            quantity=t.quantity,
            price=round(t.price / 100.0, 2),
            total_value=round(t.total_value / 100.0, 2),
            charges=round((t.charges or 0) / 100.0, 2),
            realized_pnl=round(t.realized_pnl / 100.0, 2) if t.realized_pnl is not None else None,
            reason=t.reason,
            executed_at=to_utc(t.executed_at)
        )
        for t in user_trades
    ]

@router.get('/allocation', response_model=List[SectorAllocationOut])
def allocation(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return get_sector_allocation(db, current_user.id)

@router.get('/snapshots', response_model=List[SnapshotOut])
def snapshots(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    snaps = db.query(PortfolioSnapshot).filter(PortfolioSnapshot.user_id == current_user.id).order_by(PortfolioSnapshot.date.asc()).all()
    return [
        SnapshotOut(
            date=s.date,
            cash=round(s.cash / 100.0, 2),
            holdings_value=round(s.holdings_value / 100.0, 2),
            invested=round(s.invested / 100.0, 2),
            total_value=round(s.total_value / 100.0, 2),
            realized_pnl_total=round(s.realized_pnl_total / 100.0, 2)
        )
        for s in snaps
    ]

@router.get('/wallet', response_model=List[WalletTransactionOut])
def wallet_history(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    txs = db.query(WalletTransaction).filter(WalletTransaction.user_id == current_user.id).order_by(WalletTransaction.id.desc()).all()
    return [
        WalletTransactionOut(
            id=t.id,
            type=t.type,
            amount=round(t.amount / 100.0, 2),
            balance_after=round(t.balance_after / 100.0, 2),
            ref_order_id=t.ref_order_id,
            ref_trade_id=t.ref_trade_id,
            note=t.note,
            created_at=to_utc(t.created_at)
        )
        for t in txs
    ]


@router.get('/export/trades')
def export_trades(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    trades = db.query(Trade).filter(Trade.user_id == current_user.id).order_by(Trade.id.desc()).all()
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(['id', 'order_id', 'symbol', 'side', 'product_type', 'quantity', 'price', 'total_value', 'charges', 'realized_pnl', 'reason', 'executed_at'])
    for t in trades:
        w.writerow([
            t.id, t.order_id, t.stock.symbol, t.side, t.product_type, t.quantity,
            round(t.price / 100.0, 2), round(t.total_value / 100.0, 2), round((t.charges or 0) / 100.0, 2),
            (round(t.realized_pnl / 100.0, 2) if t.realized_pnl is not None else ''),
            t.reason, t.executed_at.isoformat() if t.executed_at else '',
        ])
    buf.seek(0)
    return StreamingResponse(iter([buf.getvalue()]), media_type='text/csv', headers={'Content-Disposition': 'attachment; filename="trades.csv"'})

@router.get('/export/holdings')
def export_holdings(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    from app.models.holding import Holding as H
    holdings = db.query(H).filter(H.user_id == current_user.id).all()
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(['symbol', 'company_name', 'quantity', 'avg_buy_price', 'sector'])
    for h in holdings:
        w.writerow([h.stock.symbol, h.stock.company_name, h.quantity, round(h.avg_buy_price / 100.0, 2), h.stock.sector])
    buf.seek(0)
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=holdings.csv"})


@router.get('/benchmark')
def benchmark(range: str = '1M', db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    now = get_ist_now()
    period_map = {'1M': '1mo', '3M': '3mo', '6M': '6mo', '1Y': '1y', '1W': '5d'}
    period = period_map.get(range.upper(), '1mo')

    # Portfolio snapshots
    snaps = db.query(PortfolioSnapshot).filter(PortfolioSnapshot.user_id == current_user.id).order_by(PortfolioSnapshot.date.asc()).all()
    # filter by period roughly
    import datetime as _dt
    days = {'1W': 7, '1M': 30, '3M': 90, '6M': 180, '1Y': 365}.get(range.upper(), 30)
    cutoff = (now - _dt.timedelta(days=days)).date()
    snaps = [s for s in snaps if s.date >= cutoff]

    port_dates = [s.date.isoformat() for s in snaps]
    port_vals = [round(s.total_value / 100.0, 2) for s in snaps]

    # Benchmark: Nifty 50
    try:
        candles = price_provider.get_history('^NSEI', interval='1d', period=period) or []
    except Exception:
        candles = []
    bench_map = {}
    for c in candles:
        d = c['ts'].date() if hasattr(c['ts'], 'date') else c['ts']
        bench_map[d.isoformat() if hasattr(d, 'isoformat') else str(d)] = c['close'] / 100.0

    # align to portfolio dates if available, else use benchmark dates
    if port_dates:
        align_dates = port_dates
        # Forward-fill the benchmark onto the portfolio dates. Missing days
        # (weekends/holidays) carry the previous close forward.
        last = None
        filled = []
        for d in align_dates:
            v = bench_map.get(d)
            if v is not None:
                last = v
            filled.append(round((last if last is not None else 0), 2))
        bench_vals = filled
    else:
        align_dates = sorted(bench_map.keys())
        bench_vals = [round(bench_map[d], 2) for d in align_dates]
        port_vals = []

    # metrics
    def pct(vals):
        if len(vals) < 2 or vals[0] == 0:
            return 0.0
        return (vals[-1] / vals[0] - 1.0) * 100.0

    port_ret = pct(port_vals)
    bench_ret = pct(bench_vals)

    # beta
    import statistics
    def returns(vals):
        return [(vals[i] / vals[i-1] - 1.0) for i in range(1, len(vals)) if vals[i-1]]
    pr = returns(port_vals)
    br = returns(bench_vals)
    n = min(len(pr), len(br))
    beta = 0.0
    if n >= 2:
        pr, br = pr[-n:], br[-n:]
        meanp, meanb = statistics.mean(pr), statistics.mean(br)
        cov = sum((a - meanp) * (b - meanb) for a, b in zip(pr, br)) / n
        varb = sum((b - meanb) ** 2 for b in br) / n
        beta = cov / varb if varb else 0.0
    alpha = port_ret - beta * bench_ret
    te = 0.0
    if n >= 2:
        diffs = [a - b for a, b in zip(pr, br)]
        te = statistics.pstdev(diffs) * (252 ** 0.5) * 100.0 if len(diffs) > 1 else 0.0

    return {
        'range': range.upper(),
        'dates': align_dates,
        'portfolio': port_vals,
        'benchmark': bench_vals,
        'benchmark_name': 'Nifty 50',
        'metrics': {
            'portfolio_return_pct': round(port_ret, 2),
            'benchmark_return_pct': round(bench_ret, 2),
            'beta': round(beta, 3),
            'alpha_pct': round(alpha, 2),
            'tracking_error_pct': round(te, 2),
        },
    }
