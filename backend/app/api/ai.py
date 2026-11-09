from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.api.deps import get_db, get_current_user
from app.models.user import User
from app.models.ai_decision import AIDecision
from app.services.ai_trader import analyze, execute_decision, LLM_BASE_URL, LLM_MODEL
import os

router = APIRouter(prefix='/ai', tags=['AI Trader'])

@router.get('/status')
def status():
    try:
        import requests
        r = requests.get(f"{LLM_BASE_URL.rstrip('/')}/models", timeout=5)
        ok = r.status_code < 400
    except Exception:
        ok = False
    try:
        from app.services.agentmemory import is_available as mem_available
        mem_ok = mem_available()
    except Exception:
        mem_ok = False
    return {'reachable': ok, 'base_url': LLM_BASE_URL, 'model': LLM_MODEL, 'memory_available': mem_ok}

@router.post('/analyze')
def analyze_endpoint(payload: dict, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    symbol = (payload or {}).get('symbol', '').strip().upper()
    if not symbol:
        raise HTTPException(status_code=400, detail='symbol required')
    return analyze(db, current_user, symbol)

@router.post('/execute')
def execute_endpoint(payload: dict, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    did = (payload or {}).get('decision_id')
    if not did:
        raise HTTPException(status_code=400, detail='decision_id required')
    return execute_decision(db, current_user, int(did))

@router.get('/history')
def history(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    rows = db.query(AIDecision).filter(AIDecision.user_id == current_user.id).order_by(AIDecision.created_at.desc()).limit(50).all()
    return [
        {
            'id': r.id,
            'symbol': r.symbol,
            'action': r.action,
            'quantity': r.quantity,
            'confidence': r.confidence,
            'reasoning': r.reasoning,
            'model': r.model,
            'executed': bool(r.executed),
            'order_id': r.order_id,
            'created_at': r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]