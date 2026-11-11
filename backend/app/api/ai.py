from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.api.deps import get_db, get_current_user
from app.models.user import User
from app.models.ai_decision import AIDecision
from app.services.ai_trader import analyze, execute_decision
from app.services.ai_config import get_llm_config, set_llm_config, get_ai_config, set_ai_config
import requests
import os

router = APIRouter(prefix='/ai', tags=['AI Trader'])

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
            'dry_run': bool(r.dry_run),
            'scheduled': bool(r.scheduled),
            'guardrail_note': r.guardrail_note,
            'order_id': r.order_id,
            'created_at': r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]

@router.get('/config')
def get_config(db: Session = Depends(get_db)):
    llm = get_llm_config(db)
    ai = get_ai_config(db)
    return {'llm': llm, 'ai': ai}

@router.post('/config')
def update_config(payload: dict, db: Session = Depends(get_db)):
    if 'llm' in payload and isinstance(payload['llm'], dict):
        l = payload['llm']
        set_llm_config(db, l.get('base_url', ''), l.get('api_key', ''), l.get('model', ''))
    if 'ai' in payload and isinstance(payload['ai'], dict):
        set_ai_config(db, payload['ai'])
    return {'message': 'saved'}

@router.post('/test-connection')
def test_connection(payload: dict = None, db: Session = Depends(get_db)):
    payload = payload or {}
    if 'base_url' in payload:
        base_url = payload['base_url']
        api_key = payload.get('api_key', '')
        model = payload.get('model', '')
    else:
        c = get_llm_config(db)
        base_url, api_key, model = c['base_url'], c['api_key'], c['model']
    try:
        r = requests.get(f"{base_url.rstrip('/')}/models", headers={'Authorization': f'Bearer {api_key}'}, timeout=8)
        ok = r.status_code < 400
        models = []
        if ok:
            try:
                data = r.json()
                models = [m.get('id') for m in data.get('data', [])] if isinstance(data, dict) else []
            except Exception:
                models = []
        return {'reachable': ok, 'models': models, 'base_url': base_url, 'model': model}
    except Exception as e:
        return {'reachable': False, 'error': str(e), 'base_url': base_url, 'model': model}

@router.get('/status')
def status(db: Session = Depends(get_db)):
    c = get_llm_config(db)
    base_url, api_key, model = c['base_url'], c['api_key'], c['model']
    try:
        r = requests.get(f"{base_url.rstrip('/')}/models", headers={'Authorization': f'Bearer {api_key}'}, timeout=5)
        ok = r.status_code < 400
    except Exception:
        ok = False
    try:
        from app.services.agentmemory import is_available as mem_available
        mem_ok = mem_available()
    except Exception:
        mem_ok = False
    return {'reachable': ok, 'base_url': base_url, 'model': model, 'memory_available': mem_ok}