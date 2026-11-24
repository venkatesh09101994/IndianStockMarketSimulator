import logging
from datetime import datetime, timezone
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger
from app.db import SessionLocal
from app.config import settings
from app.models.stock import Stock, LatestQuote
from app.providers import get_active_provider
from app.services.market_clock import is_market_open, is_replay_mode, get_ist_now, IST
from app.services.order_engine import run_order_engine
from app.services.order_service import expire_pending_orders
from app.services.square_off import square_off_mis_positions
from app.services.snapshot_service import take_daily_snapshots
from app.services.ai_auto_trader import run_auto_trader
from app.services.history_service import (
    refresh_daily_history, refresh_company_info, purge_old_minute_candles
)

logger = logging.getLogger(__name__)
scheduler = BackgroundScheduler(
    timezone='Asia/Kolkata',
    job_defaults={
        'max_instances': 1,
        'coalesce': True,
        'misfire_grace_time': 300,
    },
)


def _is_same_ist_day(dt, now_ist) -> bool:
    """True when a stored UTC timestamp falls on the same IST trading day."""
    if dt is None:
        return False
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(IST).date() == now_ist.date()

def job_refresh_quotes(db=None):
    """Refresh quotes and their timestamps even outside trading hours.

    Market hours control whether orders are allowed; they must not freeze the
    market data feed. Otherwise a portable app reopened days later keeps showing
    a stale "Updated Xd ago" timestamp and stale holdings values.
    """
    owns_db = db is None
    db = db or SessionLocal()
    try:
        is_rep = is_replay_mode(db)
        provider = get_active_provider(is_rep)
        stocks = db.query(Stock).filter(Stock.is_active == True).all()
        yf_symbols = [s.yf_symbol for s in stocks]

        quotes = provider.get_quotes(yf_symbols)
        if not quotes:
            return

        now_utc = datetime.now(timezone.utc)
        now_ist = get_ist_now()
        for s in stocks:
            q_data = quotes.get(s.yf_symbol)
            if not q_data:
                continue

            quote = s.quote
            # Day high/low belong to a single session. Only extend the stored
            # values when the previous refresh happened on the same IST day,
            # otherwise reset them so they don't drift across days.
            same_day = _is_same_ist_day(quote.updated_at if quote else None, now_ist)
            if not quote:
                quote = LatestQuote(stock_id=s.id)
                db.add(quote)

            quote.price = q_data['price']
            quote.prev_close = q_data['prev_close']
            quote.open = q_data['open']
            if same_day:
                quote.day_high = max(quote.day_high or 0, q_data['day_high'])
                quote.day_low = min(quote.day_low or q_data['day_low'], q_data['day_low'])
            else:
                quote.day_high = q_data['day_high']
                quote.day_low = q_data['day_low']
            quote.volume = q_data['volume']
            quote.day_change = q_data['day_change']
            quote.day_change_pct = q_data['day_change_pct']
            quote.updated_at = now_utc

        db.commit()
        logger.info('Refreshed %d stock quotes', len(quotes))
    except Exception as e:
        db.rollback()
        logger.error(f'Error in job_refresh_quotes: {e}')
    finally:
        if owns_db:
            db.close()

def job_order_engine():
    db = SessionLocal()
    try:
        if is_market_open(db):
            run_order_engine(db)
    except Exception as e:
        logger.error(f'Error in job_order_engine: {e}')
    finally:
        db.close()

def job_square_off():
    db = SessionLocal()
    try:
        square_off_mis_positions(db)
    except Exception as e:
        logger.error(f'Error in job_square_off: {e}')
    finally:
        db.close()

def job_snapshots():
    db = SessionLocal()
    try:
        take_daily_snapshots(db)
    except Exception as e:
        logger.error(f'Error in job_snapshots: {e}')
    finally:
        db.close()

def job_ai_auto_trader():
    db = SessionLocal()
    try:
        if is_market_open(db) or is_replay_mode(db):
            run_auto_trader(db)
    except Exception as e:
        logger.error(f'Error in job_ai_auto_trader: {e}')
    finally:
        db.close()

def job_expire_day_orders():
    db = SessionLocal()
    try:
        count = expire_pending_orders(db)
        if count:
            logger.info('Expired %d pending order(s) at market close', count)
    except Exception as e:
        db.rollback()
        logger.error(f'Error in job_expire_day_orders: {e}')
    finally:
        db.close()

def job_refresh_daily_history():
    db = SessionLocal()
    try:
        # Incremental upsert: one year keeps recent candles and the trailing
        # return windows correct without re-downloading five years per stock.
        refresh_daily_history(db, period='1y')
    except Exception as e:
        db.rollback()
        logger.error(f'Error in job_refresh_daily_history: {e}')
    finally:
        db.close()

def job_refresh_company_info():
    db = SessionLocal()
    try:
        refresh_company_info(db)
    except Exception as e:
        db.rollback()
        logger.error(f'Error in job_refresh_company_info: {e}')
    finally:
        db.close()

def job_purge_minute_candles():
    db = SessionLocal()
    try:
        purge_old_minute_candles(db)
    except Exception as e:
        db.rollback()
        logger.error(f'Error in job_purge_minute_candles: {e}')
    finally:
        db.close()

def start_scheduler():
    # 1. Refresh quotes every PRICE_REFRESH_SECONDS
    scheduler.add_job(
        job_refresh_quotes,
        trigger=IntervalTrigger(seconds=settings.PRICE_REFRESH_SECONDS),
        id='refresh_quotes',
        replace_existing=True
    )

    # 2. Order engine every ORDER_ENGINE_SECONDS
    scheduler.add_job(
        job_order_engine,
        trigger=IntervalTrigger(seconds=settings.ORDER_ENGINE_SECONDS),
        id='order_engine',
        replace_existing=True
    )

    # 3. MIS Auto Square-off at 15:15 IST Mon-Fri
    scheduler.add_job(
        job_square_off,
        trigger=CronTrigger(day_of_week='mon-fri', hour=15, minute=15),
        id='square_off_mis',
        replace_existing=True
    )

    # 4. Daily Snapshot at 15:35 IST Mon-Fri
    scheduler.add_job(
        job_snapshots,
        trigger=CronTrigger(day_of_week='mon-fri', hour=15, minute=35),
        id='daily_snapshot',
        replace_existing=True
    )

    # 5. AI auto-trader every 5 minutes during market hours
    scheduler.add_job(
        job_ai_auto_trader,
        trigger=IntervalTrigger(minutes=5),
        id='ai_auto_trader',
        replace_existing=True
    )

    # 6. Expire DAY/GTT orders at 15:30 IST and release their blocked cash
    scheduler.add_job(
        job_expire_day_orders,
        trigger=CronTrigger(day_of_week='mon-fri', hour=15, minute=30),
        id='expire_day_orders',
        replace_existing=True
    )

    # 7. Refresh real daily candles + derived metrics after the session
    scheduler.add_job(
        job_refresh_daily_history,
        trigger=CronTrigger(day_of_week='mon-fri', hour=16, minute=0),
        id='refresh_daily_history',
        replace_existing=True
    )

    # 8. Refresh company metadata once a day
    scheduler.add_job(
        job_refresh_company_info,
        trigger=CronTrigger(day_of_week='mon-fri', hour=16, minute=30),
        id='refresh_company_info',
        replace_existing=True
    )

    # 9. Keep minute candles to a short retention window
    scheduler.add_job(
        job_purge_minute_candles,
        trigger=CronTrigger(hour=2, minute=0),
        id='purge_minute_candles',
        replace_existing=True
    )

    scheduler.start()
    logger.info('Background scheduler started successfully.')
