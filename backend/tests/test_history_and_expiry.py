"""Unit tests for the real-history pipeline and order expiry.

These tests use an in-memory SQLite database and never call a price provider.
"""
import os
import sys
from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.db import Base
import app.models  # noqa: F401  (registers all tables on Base.metadata)
from app.models.account import Account
from app.models.app_state import AppState
from app.models.order import Order
from app.models.stock import LatestQuote, PriceHistory, Stock
from app.models.user import User
from app.models.wallet import WalletTransaction
from app.schemas.order import OrderCreate
from app.services.history_service import recompute_quote_metrics, replace_history
from app.services.order_service import expire_pending_orders, place_order


@pytest.fixture()
def db():
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()


def _make_stock(db, symbol='TEST'):
    stock = Stock(
        symbol=symbol,
        yf_symbol=f'{symbol}.NS',
        exchange='NSE',
        company_name='Test Industries',
        sector='Information Technology',
        is_active=True,
    )
    db.add(stock)
    db.flush()
    db.add(LatestQuote(
        stock_id=stock.id,
        price=10000,
        prev_close=9900,
        open=9950,
        day_high=10100,
        day_low=9800,
        volume=1000,
        day_change=100,
        day_change_pct=1.0,
    ))
    db.commit()
    db.refresh(stock)
    return stock


def _add_daily_candles(db, stock, days=400, start=datetime(2025, 1, 1)):
    for i in range(days):
        close = 10000 + i * 10
        db.add(PriceHistory(
            stock_id=stock.id,
            interval='1d',
            ts=start + timedelta(days=i),
            open=close - 20,
            high=close + 100,
            low=close - 100,
            close=close,
            volume=1000 + i,
        ))
    db.commit()


def test_recompute_quote_metrics_uses_real_candles(db):
    stock = _make_stock(db)
    _add_daily_candles(db, stock)
    # The live quote tracks the latest candle in this fixture.
    stock.quote.price = 10000 + (400 - 1) * 10
    db.commit()

    assert recompute_quote_metrics(db, stock) is True
    quote = stock.quote

    candles = db.query(PriceHistory).filter(
        PriceHistory.stock_id == stock.id,
        PriceHistory.interval == '1d',
    ).order_by(PriceHistory.ts.asc()).all()

    anchor = candles[-1].ts
    year_candles = [c for c in candles if c.ts >= anchor - timedelta(days=365)]
    assert quote.week52_high == max(c.high for c in year_candles)
    assert quote.week52_low == min(c.low for c in year_candles)

    # 1M return is computed from the close ~30 days before the latest candle.
    base = next(c.close for c in reversed(candles) if c.ts <= anchor - timedelta(days=30))
    expected_1m = round((candles[-1].close / base - 1.0) * 100.0, 2)
    assert quote.return_1m_pct == expected_1m

    recent_volumes = [c.volume for c in candles[-20:]]
    assert quote.avg_volume_20d == int(sum(recent_volumes) / len(recent_volumes))


def test_replace_history_removes_synthetic_rows(db):
    stock = _make_stock(db)
    # A seeded-style series that includes a weekend date.
    fake = [
        {'ts': datetime(2025, 1, 3), 'open': 1, 'high': 2, 'low': 1, 'close': 2, 'volume': 10},
        {'ts': datetime(2025, 1, 4), 'open': 1, 'high': 2, 'low': 1, 'close': 2, 'volume': 10},  # Saturday
        {'ts': datetime(2025, 1, 5), 'open': 1, 'high': 2, 'low': 1, 'close': 2, 'volume': 10},  # Sunday
    ]
    assert replace_history(db, stock.id, '1d', fake) == 3

    real = [
        {'ts': datetime(2025, 1, 6), 'open': 10, 'high': 20, 'low': 9, 'close': 15, 'volume': 100},
        {'ts': datetime(2025, 1, 7), 'open': 15, 'high': 25, 'low': 14, 'close': 20, 'volume': 200},
    ]
    assert replace_history(db, stock.id, '1d', real) == 2

    rows = db.query(PriceHistory).filter(PriceHistory.stock_id == stock.id).all()
    assert len(rows) == 2
    assert {r.ts for r in rows} == {datetime(2025, 1, 6), datetime(2025, 1, 7)}


def test_expire_pending_orders_releases_blocked_cash(db):
    stock = _make_stock(db, symbol='EXPIRY')
    user = User(name='Trader', email='expiry@example.com', password_hash='x')
    db.add(user)
    db.flush()
    account = Account(
        user_id=user.id,
        cash_balance=100000,
        starting_balance=100000,
        realized_pnl_total=0,
    )
    db.add(account)
    order = Order(
        user_id=user.id,
        stock_id=stock.id,
        side='BUY',
        product_type='CNC',
        order_type='LIMIT',
        quantity=10,
        limit_price=10000,
        status='PENDING',
        blocked_amount=25000,
        validity='DAY',
        expires_at=datetime(2020, 1, 1),
        created_at=datetime(2020, 1, 1),
    )
    db.add(order)
    db.commit()

    expired = expire_pending_orders(db)
    assert expired == 1
    db.refresh(order)
    db.refresh(account)

    assert order.status == 'EXPIRED'
    assert order.blocked_amount == 0
    assert account.cash_balance == 125000
    release = db.query(WalletTransaction).filter(
        WalletTransaction.user_id == user.id,
        WalletTransaction.type == 'ORDER_RELEASE',
    ).one()
    assert release.amount == 25000


def _enable_replay(db):
    db.add(AppState(key='replay_mode', value='true'))
    db.commit()


def test_order_rejected_when_no_quote_exists(db):
    """A missing quote must block the order instead of using a fake price."""
    _enable_replay(db)
    stock = Stock(
        symbol='NOQUOTE',
        yf_symbol='NOQUOTE.NS',
        exchange='NSE',
        company_name='No Quote Ltd',
        is_active=True,
    )
    db.add(stock)
    user = User(name='Trader', email='noquote@example.com', password_hash='x')
    db.add(user)
    db.flush()
    account = Account(
        user_id=user.id,
        cash_balance=100000,
        starting_balance=100000,
        realized_pnl_total=0,
    )
    db.add(account)
    db.commit()

    with pytest.raises(ValueError, match='No live quote'):
        place_order(db, user.id, OrderCreate(
            symbol='NOQUOTE',
            side='BUY',
            product_type='CNC',
            order_type='MARKET',
            quantity=1,
        ))

    db.rollback()
    db.refresh(account)
    assert account.cash_balance == 100000
    assert db.query(Order).filter(Order.user_id == user.id).count() == 0


def test_day_order_expiry_is_next_market_close():
    """DAY orders expire at 15:30 IST; GTT orders live for a year."""
    from app.services.order_service import _expiry_for

    day_expiry = _expiry_for('DAY')
    assert day_expiry.hour == 10  # 15:30 IST == 10:00 UTC
    assert day_expiry.minute == 0

    gtt_expiry = _expiry_for('GTT')
    assert (gtt_expiry - day_expiry).days >= 300
