import logging
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from app.models.position import Position
from app.models.order import Order
from app.models.stock import LatestQuote
from app.services.execution_service import execute_order
from app.services.market_clock import get_ist_now

logger = logging.getLogger(__name__)

def square_off_mis_positions(db: Session):
    logger.info('Starting automated MIS square-off...')
    from app.models.account import Account
    from app.models.wallet import WalletTransaction
    pending_mis = db.query(Order).filter(
        Order.product_type == 'MIS',
        Order.status == 'PENDING'
    ).all()
    for o in pending_mis:
        if o.blocked_amount and o.blocked_amount > 0:
            acc = db.query(Account).filter(Account.user_id == o.user_id).first()
            if acc:
                acc.cash_balance += o.blocked_amount
                db.add(WalletTransaction(
                    user_id=o.user_id,
                    type='ORDER_RELEASE',
                    amount=o.blocked_amount,
                    balance_after=acc.cash_balance,
                    ref_order_id=o.id,
                    note=f'Released blocked funds on auto square-off cancel #{o.id}'
                ))
            o.blocked_amount = 0
        o.status = 'CANCELLED'
        o.reject_reason = 'Auto square-off cancellation'

    db.commit()

    open_positions = db.query(Position).filter(
        Position.is_open == True,
        Position.net_quantity != 0
    ).all()

    for pos in open_positions:
        try:
            quote = db.query(LatestQuote).filter(LatestQuote.stock_id == pos.stock_id).first()
            fill_price = quote.price if quote else pos.avg_price

            close_side = 'SELL' if pos.net_quantity > 0 else 'BUY'
            close_qty = abs(pos.net_quantity)

            so_order = Order(
                user_id=pos.user_id,
                stock_id=pos.stock_id,
                side=close_side,
                product_type='MIS',
                order_type='MARKET',
                quantity=close_qty,
                status='PENDING',
                created_at=datetime.now(timezone.utc)
            )
            db.add(so_order)
            db.flush()

            execute_order(db, so_order, fill_price=fill_price, reason='SQUARE_OFF')
            db.commit()
            logger.info(f'Auto squared off position #{pos.id} for user #{pos.user_id}')
        except Exception as e:
            db.rollback()
            logger.error(f'Failed to auto square-off position #{pos.id}: {e}')
