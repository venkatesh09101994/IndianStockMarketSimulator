from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.api.deps import get_db, get_current_user
from app.models.user import User
from app.models.account import Account
from app.models.order import Order
from app.models.trade import Trade
from app.models.holding import Holding
from app.models.position import Position
from app.models.wallet import WalletTransaction
from app.models.snapshot import PortfolioSnapshot
from app.models.watchlist import WatchlistItem
from app.models.ai_decision import AIDecision
from app.models.app_state import AppState
from app.schemas.admin import AccountResetRequest, AccountResetResponse

router = APIRouter(tags=['Admin'])

# Default reset capital: Rs 1,00,000 (1 lakh).
DEFAULT_RESET_PAISE = 100000 * 100
MIN_RESET_RUPEES = 1.0
MAX_RESET_RUPEES = 100_00_00_000.0  # Rs 100 crore safety cap

@router.post('/admin/replay/start')
def start_replay(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    state = db.query(AppState).filter(AppState.key == 'replay_mode').first()
    if not state:
        state = AppState(key='replay_mode', value='true')
        db.add(state)
    else:
        state.value = 'true'
    db.commit()
    return {'message': 'Replay mode enabled', 'replay_mode': True}

@router.post('/admin/replay/stop')
def stop_replay(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    state = db.query(AppState).filter(AppState.key == 'replay_mode').first()
    if state:
        state.value = 'false'
        db.commit()
    return {'message': 'Replay mode disabled', 'replay_mode': False}

@router.post('/account/reset', response_model=AccountResetResponse)
def reset_user_account(
    payload: AccountResetRequest | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    requested = payload.amount if payload else None
    amount_rupees = DEFAULT_RESET_PAISE / 100.0 if requested is None else float(requested)
    if amount_rupees < MIN_RESET_RUPEES or amount_rupees > MAX_RESET_RUPEES:
        raise HTTPException(
            status_code=400,
            detail=(
                f'Reset amount must be between Rs {MIN_RESET_RUPEES:,.0f} and '
                f'Rs {MAX_RESET_RUPEES:,.0f}'
            ),
        )
    new_paise = int(round(amount_rupees * 100))

    uid = current_user.id
    db.query(Trade).filter(Trade.user_id == uid).delete()
    db.query(Order).filter(Order.user_id == uid).delete()
    db.query(Holding).filter(Holding.user_id == uid).delete()
    db.query(Position).filter(Position.user_id == uid).delete()
    db.query(WalletTransaction).filter(WalletTransaction.user_id == uid).delete()
    db.query(PortfolioSnapshot).filter(PortfolioSnapshot.user_id == uid).delete()
    db.query(WatchlistItem).filter(WatchlistItem.user_id == uid).delete()
    db.query(AIDecision).filter(AIDecision.user_id == uid).delete()

    acc = db.query(Account).filter(Account.user_id == uid).first()
    if acc:
        acc.cash_balance = new_paise
        # The reset capital is the new baseline for overall return, otherwise
        # portfolio performance would be measured against the old amount.
        acc.starting_balance = new_paise
        acc.realized_pnl_total = 0

    db.add(WalletTransaction(
        user_id=uid,
        type='RESET',
        amount=new_paise,
        balance_after=new_paise,
        note=f'Account reset with Rs {amount_rupees:,.2f} virtual capital'
    ))

    db.commit()
    new_balance = round(new_paise / 100.0, 2)
    return AccountResetResponse(
        message='Account has been successfully reset.',
        new_balance=new_balance,
        starting_balance=new_balance,
    )
