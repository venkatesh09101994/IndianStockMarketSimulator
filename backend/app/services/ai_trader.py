import os
import json
import requests
import logging
from typing import Optional, Dict, Any
from sqlalchemy.orm import Session
from app.config import settings
from app.models.stock import Stock, LatestQuote, PriceHistory
from app.models.ai_decision import AIDecision
from app.models.user import User

logger = logging.getLogger(__name__)

from app.config import settings as _cfg

def _llm(db=None):
    if db is not None:
        try:
            from app.services.ai_config import get_llm_config
            c = get_llm_config(db)
            return c['base_url'], c['api_key'], c['model']
        except Exception:
            pass
    return _cfg.LLM_BASE_URL, _cfg.LLM_API_KEY, _cfg.LLM_MODEL

LLM_BASE_URL, LLM_API_KEY, LLM_MODEL = _llm()

def _get_quote_and_history(db: Session, symbol: str) -> Optional[Dict[str, Any]]:
    stock = db.query(Stock).filter(Stock.symbol == symbol.upper()).first()
    if not stock:
        return None
    quote = stock.quote
    history = db.query(PriceHistory).filter(PriceHistory.stock_id == stock.id, PriceHistory.interval == '1d').order_by(PriceHistory.ts.desc()).limit(10).all()
    hist = [{'date': h.ts.strftime('%Y-%m-%d') if h.ts else '', 'close': h.close / 100.0, 'volume': h.volume} for h in reversed(history)]
    return {
        'symbol': stock.symbol,
        'company': stock.company_name,
        'sector': stock.sector,
        'price': (quote.price / 100.0) if quote else None,
        'prev_close': (quote.prev_close / 100.0) if quote else None,
        'day_change_pct': quote.day_change_pct if quote else None,
        'volume': quote.volume if quote else None,
        'week52_high': (quote.week52_high / 100.0) if quote else None,
        'week52_low': (quote.week52_low / 100.0) if quote else None,
        'history': hist,
    }

def _build_prompt(ctx: Dict[str, Any], cash_balance: float, holdings_qty: int, memory_context: str = '', graph_context: str = '') -> str:
    hist_str = '\n'.join(f"  {h['date']}: close={h['close']}, vol={h['volume']}" for h in ctx['history']) or '  (no history)'
    memory_block = ''
    if memory_context:
        memory_block = 'Past decisions & lessons from memory:\n' + memory_context + '\n\n'
    graph_block = ''
    if graph_context:
        graph_block = 'Knowledge graph context:\n  ' + graph_context + '\n\n'
    return (
        "You are an autonomous Indian stock market trading agent. Analyze the following stock and decide whether to BUY, SELL, or HOLD.\n\n"
        f"Stock: {ctx['symbol']} ({ctx['company']}) - Sector: {ctx['sector']}\n"
        f"Current Price: {ctx['price']}\n"
        f"Prev Close: {ctx['prev_close']}\n"
        f"Day Change %: {ctx['day_change_pct']}\n"
        f"Volume: {ctx['volume']}\n"
        f"52W High: {ctx['week52_high']}  52W Low: {ctx['week52_low']}\n\n"
        "Recent price history (last 10 sessions):\n"
        f"{hist_str}\n\n"
        "Portfolio context:\n"
        f"  Available cash (INR): {cash_balance}\n"
        f"  Current holdings of {ctx['symbol']}: {holdings_qty} shares\n\n"
        + memory_block
        + graph_block
        + "Risk rules (MUST follow):\n"
        "  - Never use more than 20% of available cash in a single trade.\n"
        "  - Quantity must be a positive integer and affordable with available cash.\n"
        "  - If no clear edge, choose HOLD with quantity 0.\n\n"
        'Respond ONLY with a valid JSON object (no markdown, no extra text) in this exact format:\n'
        '{"action": "BUY"|"SELL"|"HOLD", "quantity": <integer>, "confidence": <0.0-1.0>, "reasoning": "<short explanation>"}'
    )

def analyze(db: Session, user: User, symbol: str) -> Dict[str, Any]:
    ctx = _get_quote_and_history(db, symbol)
    if not ctx or ctx['price'] is None:
        return {'error': f'Stock {symbol} not found or no quote'}

    # holdings qty
    from app.models.holding import Holding
    from app.models.stock import Stock as _Stock
    st = db.query(_Stock).filter(_Stock.symbol == symbol.upper()).first()
    h = db.query(Holding).filter(Holding.user_id == user.id, Holding.stock_id == (st.id if st else None)).first() if st else None

    # Recall relevant memories from agentmemory (if available)
    memory_context = ''
    try:
        from app.services.agentmemory import recall, is_available
        if is_available():
            mems = recall(f'past trades and lessons for {symbol.upper()}', limit=5, project='stock-simulator')
            if mems:
                memory_context = '\n'.join(f"  - {m.get('title','')}" for m in mems if m.get('title'))
    except Exception:
        memory_context = ''

    # Knowledge graph context (related stocks / sector peers)
    graph_context = ''
    try:
        from app.services.stock_graph import load_graph, build_graph, neighbors, sector_peers
        g = load_graph()
        if not g:
            try:
                g = build_graph(db)
            except Exception:
                g = None
        if g:
            nbrs = neighbors(symbol.upper(), g)
            peers = sector_peers(symbol.upper(), g)
            parts = []
            if peers:
                parts.append('Sector peers: ' + ', '.join(peers))
            if nbrs:
                corr = [n['symbol'] for n in nbrs if n['relation'] == 'correlated']
                if corr:
                    parts.append('Highly correlated stocks: ' + ', '.join(corr[:6]))
            graph_context = '; '.join(parts)
    except Exception:
        graph_context = ''
    holdings_qty = h.quantity if h else 0
    cash = user.account.cash_balance / 100.0 if user.account else 0.0

    base_url, api_key, model = _llm(db)
    prompt = _build_prompt(ctx, cash, holdings_qty, memory_context, graph_context)

    try:
        resp = requests.post(
            f"{base_url.rstrip('/')}/chat/completions",
            headers={'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'},
            json={
                'model': model,
                'messages': [{'role': 'user', 'content': prompt}],
                'temperature': 0.2,
            },
            timeout=180,
        )
        resp.raise_for_status()
        data = resp.json()
        content = data['choices'][0]['message']['content'].strip()
        # strip code fences if present
        if content.startswith('```'):
            content = content.strip('`').strip()
            if content.lower().startswith('json'):
                content = content[4:].strip()
        decision = json.loads(content)
    except Exception as e:
        logger.exception('LLM call failed')
        return {'error': f'LLM error: {e}', 'model': model}

    action = str(decision.get('action', 'HOLD')).upper()
    if action not in ('BUY', 'SELL', 'HOLD'):
        action = 'HOLD'
    quantity = int(decision.get('quantity', 0) or 0)
    confidence = float(decision.get('confidence', 0.0) or 0.0)
    reasoning = str(decision.get('reasoning', ''))

    # Enforce risk rules / affordability
    price = ctx['price']
    if action == 'BUY' and price and price > 0:
        max_qty = int((cash * 0.20) / price)  # at most 20% of cash per trade
        if max_qty < 1:
            max_qty = 0
        quantity = max(0, min(quantity, max_qty))
        if quantity == 0:
            action = 'HOLD'
            reasoning = reasoning + ' [Capped: insufficient cash for even 1 share within 20% limit]'
    elif action == 'SELL':
        quantity = max(0, min(quantity, holdings_qty))

    # persist
    row = AIDecision(
        user_id=user.id,
        symbol=symbol.upper(),
        action=action,
        quantity=quantity,
        confidence=confidence,
        reasoning=reasoning,
        model=model,
        executed=0,
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    return {
        'id': row.id,
        'symbol': symbol.upper(),
        'action': action,
        'quantity': quantity,
        'confidence': confidence,
        'reasoning': reasoning,
        'model': model,
        'context': ctx,
        'memory_context': memory_context,
        'graph_context': graph_context,
        'memory_available': __import__('app.services.agentmemory', fromlist=['is_available']).is_available(),
    }

def execute_decision(db: Session, user: User, decision_id: int) -> Dict[str, Any]:
    row = db.query(AIDecision).filter(AIDecision.id == decision_id, AIDecision.user_id == user.id).first()
    if not row:
        return {'error': 'Decision not found'}
    if row.action == 'HOLD':
        row.executed = 1
        db.commit()
        return {'message': 'HOLD - no order placed', 'decision_id': row.id}
    if row.quantity <= 0:
        return {'error': 'Quantity must be > 0'}

    # Use existing order service
    from app.services.order_service import place_order
    from app.schemas.order import OrderCreate
    order_in = OrderCreate(
        symbol=row.symbol,
        side=row.action,
        product_type='CNC',
        order_type='MARKET',
        quantity=row.quantity,
    )
    try:
        order = place_order(db, user.id, order_in)
        row.executed = 1
        row.order_id = order.id
        db.commit()
        # Persist to agentmemory for future recall
        try:
            from app.services.agentmemory import remember, is_available
            if is_available():
                remember(
                    content=f"AI {row.action} {row.quantity} {row.symbol} @ {getattr(order,'execution_price',None)}. Confidence {row.confidence}. Reasoning: {row.reasoning}. Model: {row.model}.",
                    concepts=[row.symbol, row.action, row.model, 'trade'],
                    project='stock-simulator',
                )
        except Exception:
            pass
        return {
            'message': f'{row.action} executed',
            'decision_id': row.id,
            'order_id': order.id,
            'symbol': row.symbol,
            'side': row.action,
            'quantity': row.quantity,
            'execution_price': getattr(order, 'execution_price', None),
            'status': getattr(order, 'status', None),
        }
    except Exception as e:
        logger.exception('Order execution failed')
        return {'error': f'Execution failed: {e}'}