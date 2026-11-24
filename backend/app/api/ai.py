from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.api.deps import get_db, get_current_user
from app.models.user import User
from app.models.ai_decision import AIDecision
from app.services.ai_trader import analyze, execute_decision
from app.services.multi_agent import debate as multi_debate
from app.services.ai_config import get_llm_config, set_llm_config, get_ai_config, set_ai_config
from app.utils.time import to_utc
import requests

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
    try:
        did = int(did)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail='decision_id must be an integer')
    return execute_decision(db, current_user, did)

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
            'created_at': to_utc(r.created_at).isoformat() if r.created_at else None,
        }
        for r in rows
    ]

@router.get('/config')
def get_config(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    llm = get_llm_config(db)
    ai = get_ai_config(db)
    return {'llm': llm, 'ai': ai}

@router.post('/config')
def update_config(payload: dict, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if 'llm' in payload and isinstance(payload['llm'], dict):
        l = payload['llm']
        set_llm_config(db, l.get('base_url', ''), l.get('api_key', ''), l.get('model', ''))
    if 'ai' in payload and isinstance(payload['ai'], dict):
        set_ai_config(db, payload['ai'])
    return {'message': 'saved'}

@router.post('/test-connection')
def test_connection(payload: dict = None, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    payload = payload or {}
    stored = get_llm_config(db, reveal=True)
    if 'base_url' in payload:
        base_url = payload.get('base_url') or stored['base_url']
        api_key = payload.get('api_key') or ''
        model = payload.get('model') or stored['model']
    else:
        base_url, api_key, model = stored['base_url'], stored['api_key'], stored['model']
    # The browser only ever receives a masked key; fall back to the stored one
    # when the user tests the connection without re-entering it.
    if not api_key or '•' in api_key:
        api_key = stored['api_key']
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

@router.post('/debate')
def debate_endpoint(payload: dict, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    symbol = (payload or {}).get('symbol', '').strip().upper()
    if not symbol:
        raise HTTPException(status_code=400, detail='symbol required')
    return multi_debate(db, current_user, symbol)

@router.post('/evaluate')
def evaluate_outcomes(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    # mark was_correct for executed decisions that have a realized pnl
    from app.models.trade import Trade
    from app.models.ai_decision import AIDecision
    rows = db.query(AIDecision).filter(AIDecision.user_id == current_user.id, AIDecision.executed == 1).all()
    updated = 0
    for r in rows:
        if r.was_correct is not None:
            continue
        if not r.order_id:
            continue
        trade = db.query(Trade).filter(Trade.order_id == r.order_id).first()
        if not trade or trade.realized_pnl is None:
            continue
        pnl = trade.realized_pnl
        if r.action == 'BUY':
            correct = 1 if pnl > 0 else 0
        elif r.action == 'SELL':
            correct = 1 if pnl > 0 else 0
        else:
            continue
        r.was_correct = correct
        r.outcome_pnl = pnl
        updated += 1
    db.commit()
    return {'updated': updated}

@router.get('/accuracy')
def accuracy(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    from app.models.ai_decision import AIDecision
    rows = db.query(AIDecision).filter(AIDecision.user_id == current_user.id, AIDecision.executed == 1).all()
    total = len(rows)
    evaluated = [r for r in rows if r.was_correct is not None]
    correct = sum(1 for r in evaluated if r.was_correct == 1)
    return {
        'total_executed': total,
        'evaluated': len(evaluated),
        'correct': correct,
        'accuracy_pct': round(correct / len(evaluated) * 100.0, 2) if evaluated else 0.0,
    }

@router.get('/status')
def status(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    c = get_llm_config(db, reveal=True)
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