from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.api.deps import get_db, get_current_user
from app.models.user import User
from app.services.backtest import run_backtest

router = APIRouter(prefix='/backtest', tags=['Backtest'])

@router.post('/run')
def run(payload: dict, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    symbol = (payload or {}).get('symbol', '').strip().upper()
    strategy = (payload or {}).get('strategy', 'sma_crossover')
    params = (payload or {}).get('params', {}) or {}
    period_days = int((payload or {}).get('period_days', 252))
    if not symbol:
        raise HTTPException(status_code=400, detail='symbol required')
    result = run_backtest(db, symbol, strategy, params, period_days)
    if 'error' in result:
        raise HTTPException(status_code=400, detail=result['error'])
    return result