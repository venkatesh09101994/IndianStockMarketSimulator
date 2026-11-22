import logging
from sqlalchemy.orm import Session
from app.models.order import Order
from app.models.stock import LatestQuote
from app.services.execution_service import execute_order

logger = logging.getLogger(__name__)


def run_order_engine(db: Session):
    order_ids = [row[0] for row in db.query(Order.id).filter(Order.status == 'PENDING').all()]
    if not order_ids:
        return

    for order_id in order_ids:
        # Clear any state left by a previous failed fill before starting this
        # one, then work from a freshly loaded order.
        db.rollback()
        try:
            order = db.query(Order).filter(
                Order.id == order_id,
                Order.status == 'PENDING'
            ).first()
            if not order:
                continue

            quote = db.query(LatestQuote).filter(LatestQuote.stock_id == order.stock_id).first()
            if not quote:
                continue

            cur_price = quote.price

            # Day high/low are cumulative for the session. Only a move beyond
            # the snapshot taken when the order was placed counts as a new
            # touch; otherwise an old extreme could fill a newer order.
            base_high = order.placed_day_high if order.placed_day_high is not None else cur_price
            base_low = order.placed_day_low if order.placed_day_low is not None else cur_price
            new_high = quote.day_high if quote.day_high > base_high else None
            new_low = quote.day_low if quote.day_low < base_low else None

            matched = False
            fill_price = cur_price
            reason = 'LIMIT_HIT'

            if order.order_type == 'MARKET':
                # MARKET orders normally fill in place_order; retry any that
                # were left PENDING by a transient failure so they cannot stick.
                matched = True
                reason = 'MARKET_RETRY'

            elif order.order_type == 'LIMIT' and order.limit_price is not None:
                if order.side == 'BUY':
                    if cur_price <= order.limit_price:
                        matched = True
                        fill_price = min(order.limit_price, cur_price)
                    elif new_low is not None and new_low <= order.limit_price:
                        matched = True
                        fill_price = min(order.limit_price, new_low)
                elif order.side == 'SELL':
                    if cur_price >= order.limit_price:
                        matched = True
                        fill_price = max(order.limit_price, cur_price)
                    elif new_high is not None and new_high >= order.limit_price:
                        matched = True
                        fill_price = max(order.limit_price, new_high)

            elif order.order_type == 'SL_M' and order.trigger_price is not None:
                reason = 'SL_HIT'
                if order.side == 'SELL':
                    if cur_price <= order.trigger_price:
                        matched = True
                        fill_price = cur_price
                    elif new_low is not None and new_low <= order.trigger_price:
                        matched = True
                        fill_price = new_low
                elif order.side == 'BUY':
                    if cur_price >= order.trigger_price:
                        matched = True
                        fill_price = cur_price
                    elif new_high is not None and new_high >= order.trigger_price:
                        matched = True
                        fill_price = new_high

            if not matched:
                continue

            # Re-check immediately before the fill: another engine run may
            # have executed this order since the list of IDs was read.
            fresh_order = db.query(Order).filter(
                Order.id == order_id,
                Order.status == 'PENDING'
            ).first()
            if not fresh_order:
                continue

            logger.info(
                f'Filling order #{order_id} for {fresh_order.stock.symbol} '
                f'@ Rs {fill_price / 100:.2f} ({reason})'
            )
            execute_order(db, fresh_order, fill_price=fill_price, reason=reason)
            db.commit()

        except Exception as e:
            db.rollback()
            logger.error(f'Error evaluating order #{order_id}: {e}')
