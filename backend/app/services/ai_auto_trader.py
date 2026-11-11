"""Scheduled AI auto-trader: runs analysis on a watchlist with guardrails."""
import logging
from datetime import datetime, timezone, timedelta
from sqlalchemy.orm import Session
from app.models.user import User
from app.models.ai_decision import AIDecision
from app.services.ai_trader import analyze, execute_decision
from app.services.ai_config import get_ai_config
from app.services.market_clock import get_ist_now, is_market_open, is_replay_mode

logger = logging.getLogger(__name__)


def _trades_today(db: Session, user_id: int) -> int:
    today = get_ist_now().date()
    rows = db.query(AIDecision).filter(
        AIDecision.user_id == user_id,
        AIDecision.scheduled == 1,
        AIDecision.executed == 1,
    ).all()
    cnt = 0
    for r in rows:
        dt = r.created_at
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        if dt.astimezone(__import__('zoneinfo').ZoneInfo('Asia/Kolkata')).date() == today:
            cnt += 1
    return cnt


def _last_executed_for_symbol(db: Session, user_id: int, symbol: str):
    r = (db.query(AIDecision)
         .filter(AIDecision.user_id == user_id, AIDecision.symbol == symbol, AIDecision.executed == 1)
         .order_by(AIDecision.created_at.desc())
         .first())
    return r.created_at if r else None


def run_auto_trader(db: Session):
    if not is_market_open(db) and not is_replay_mode(db):
        return
    # single default user: first user
    user = db.query(User).first()
    if not user:
        return
    cfg = get_ai_config(db)
    if not cfg['enabled'] or not cfg['watchlist']:
        return

    if _trades_today(db, user.id) >= cfg['max_trades_per_day']:
        logger.info('AI auto-trader: daily trade cap reached')
        return

    now = datetime.now(timezone.utc)
    cooldown = timedelta(minutes=cfg['cooldown_minutes'])

    for symbol in cfg['watchlist']:
        if _trades_today(db, user.id) >= cfg['max_trades_per_day']:
            break
        last = _last_executed_for_symbol(db, user.id, symbol)
        if last is not None:
            if last.tzinfo is None:
                last = last.replace(tzinfo=timezone.utc)
            if now - last < cooldown:
                continue
        try:
            result = analyze(db, user, symbol)
        except Exception as e:
            logger.warning(f'AI analyze failed for {symbol}: {e}')
            continue
        if 'error' in result:
            logger.warning(f'AI analyze error {symbol}: {result.get("error")}')
            continue
        action = result.get('action')
        qty = result.get('quantity', 0)
        conf = result.get('confidence', 0.0)
        did = result.get('id')
        if action not in ('BUY', 'SELL') or qty <= 0:
            continue
        if conf < cfg['min_confidence']:
            # mark guardrail
            row = db.query(AIDecision).filter(AIDecision.id == did).first()
            if row:
                row.guardrail_note = f'Below min confidence {conf:.2f} < {cfg["min_confidence"]}'
                db.commit()
            continue

        row = db.query(AIDecision).filter(AIDecision.id == did).first()
        if row:
            row.scheduled = 1
            row.dry_run = 1 if cfg['dry_run'] else 0
            db.commit()

        if cfg['dry_run']:
            logger.info(f'AI auto-trader (dry-run): {action} {qty} {symbol} conf={conf:.2f}')
            continue
        try:
            execute_decision(db, user, did)
            logger.info(f'AI auto-trader executed: {action} {qty} {symbol}')
        except Exception as e:
            logger.warning(f'AI execute failed {symbol}: {e}')
