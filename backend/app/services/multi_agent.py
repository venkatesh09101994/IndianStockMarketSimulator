"""Multi-agent debate: bullish, bearish, risk manager, then a judge."""
import json
import logging
import requests
from typing import Dict, Any
from sqlalchemy.orm import Session
from app.models.user import User
from app.models.ai_decision import AIDecision
from app.services.ai_trader import _get_quote_and_history
from app.services.ai_config import get_llm_config
from app.services.agentmemory import recall, is_available as mem_available
from app.services.stock_graph import load_graph, build_graph, neighbors, sector_peers

logger = logging.getLogger(__name__)


def _llm_call(base_url, api_key, model, prompt, temperature=0.3):
    resp = requests.post(
        f"{base_url.rstrip('/')}/chat/completions",
        headers={'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'},
        json={'model': model, 'messages': [{'role': 'user', 'content': prompt}], 'temperature': temperature},
        timeout=180,
    )
    resp.raise_for_status()
    data = resp.json()
    content = data['choices'][0]['message']['content'].strip()
    if content.startswith('```'):
        content = content.strip('`').strip()
        if content.lower().startswith('json'):
            content = content[4:].strip()
    return json.loads(content)


def debate(db: Session, user: User, symbol: str) -> Dict[str, Any]:
    ctx = _get_quote_and_history(db, symbol)
    if not ctx or ctx['price'] is None:
        return {'error': f'Stock {symbol} not found or no quote'}

    # memory + graph context (same as single agent)
    memory_context = ''
    if mem_available():
        try:
            mems = recall(f'past trades and lessons for {symbol.upper()}', limit=5, project='stock-simulator')
            memory_context = '\n'.join(f"  - {m.get('title','')}" for m in mems if m.get('title'))
        except Exception:
            memory_context = ''
    graph_context = ''
    try:
        g = load_graph() or build_graph(db)
        if g:
            nbrs = neighbors(symbol.upper(), g)
            peers = sector_peers(symbol.upper(), g)
            parts = []
            if peers:
                parts.append('Sector peers: ' + ', '.join(peers))
            corr = [n['symbol'] for n in nbrs if n['relation'] == 'correlated']
            if corr:
                parts.append('Highly correlated stocks: ' + ', '.join(corr[:6]))
            graph_context = '; '.join(parts)
    except Exception:
        graph_context = ''

    from app.models.holding import Holding
    from app.models.stock import Stock as _Stock
    st = db.query(_Stock).filter(_Stock.symbol == symbol.upper()).first()
    h = db.query(Holding).filter(Holding.user_id == user.id, Holding.stock_id == (st.id if st else None)).first() if st else None
    holdings_qty = h.quantity if h else 0
    cash = user.account.cash_balance / 100.0 if user.account else 0.0

    c = get_llm_config(db, reveal=True)
    base_url, api_key, model = c['base_url'], c['api_key'], c['model']

    # Bullish agent
    bull_prompt = (
        "You are a BULLISH equity analyst. Argue why this Indian stock should be BOUGHT.\n"
        f"Stock: {ctx['symbol']} ({ctx['company']}) Sector: {ctx['sector']}\n"
        f"Price: {ctx['price']}  Day change %: {ctx['day_change_pct']}  Volume: {ctx['volume']}\n"
        f"52W High: {ctx['week52_high']} Low: {ctx['week52_low']}\n"
        f"Available cash INR: {cash}  Current holdings: {holdings_qty}\n"
        + (f"Memory: {memory_context}\n" if memory_context else '')
        + (f"Graph: {graph_context}\n" if graph_context else '')
        + "Respond ONLY JSON: {\"stance\":\"BUY\",\"confidence\":0.0-1.0,\"reasoning\":\"...\"}"
    )
    # Bearish agent
    bear_prompt = (
        "You are a BEARISH equity analyst. Argue why this Indian stock should be SOLD or avoided.\n"
        f"Stock: {ctx['symbol']} ({ctx['company']}) Sector: {ctx['sector']}\n"
        f"Price: {ctx['price']}  Day change %: {ctx['day_change_pct']}  Volume: {ctx['volume']}\n"
        f"52W High: {ctx['week52_high']} Low: {ctx['week52_low']}\n"
        f"Available cash INR: {cash}  Current holdings: {holdings_qty}\n"
        + (f"Memory: {memory_context}\n" if memory_context else '')
        + (f"Graph: {graph_context}\n" if graph_context else '')
        + "Respond ONLY JSON: {\"stance\":\"SELL\",\"confidence\":0.0-1.0,\"reasoning\":\"...\"}"
    )
    # Risk manager
    risk_prompt = (
        "You are a RISK MANAGER. Evaluate downside risks, volatility, and position sizing. Recommend HOLD/BUY/SELL with caution.\n"
        f"Stock: {ctx['symbol']} ({ctx['company']}) Sector: {ctx['sector']}\n"
        f"Price: {ctx['price']}  Day change %: {ctx['day_change_pct']}  Volume: {ctx['volume']}\n"
        f"Available cash INR: {cash}  Current holdings: {holdings_qty}\n"
        + (f"Graph: {graph_context}\n" if graph_context else '')
        + "Respond ONLY JSON: {\"stance\":\"HOLD\"|\"BUY\"|\"SELL\",\"confidence\":0.0-1.0,\"reasoning\":\"...\"}"
    )

    agents = {}
    for name, prompt in [('bull', bull_prompt), ('bear', bear_prompt), ('risk', risk_prompt)]:
        try:
            agents[name] = _llm_call(base_url, api_key, model, prompt)
        except Exception as e:
            agents[name] = {'stance': 'HOLD', 'confidence': 0.0, 'reasoning': f'LLM error: {e}'}

    # Judge
    judge_prompt = (
        "You are a JUDGE. Three analysts debated an Indian stock. Decide final action.\n"
        f"Stock: {ctx['symbol']} ({ctx['company']}) Price: {ctx['price']}\n"
        f"Bull: {agents['bull'].get('stance')} conf {agents['bull'].get('confidence')} - {agents['bull'].get('reasoning')}\n"
        f"Bear: {agents['bear'].get('stance')} conf {agents['bear'].get('confidence')} - {agents['bear'].get('reasoning')}\n"
        f"Risk: {agents['risk'].get('stance')} conf {agents['risk'].get('confidence')} - {agents['risk'].get('reasoning')}\n"
        f"Available cash INR: {cash}  Holdings: {holdings_qty}\n"
        "Risk rules: never use more than 20% of cash in one trade; whole shares only; if no edge choose HOLD qty 0.\n"
        "Respond ONLY JSON: {\"action\":\"BUY\"|\"SELL\"|\"HOLD\",\"quantity\":<int>,\"confidence\":0.0-1.0,\"reasoning\":\"<short>\"}"
    )
    try:
        verdict = _llm_call(base_url, api_key, model, judge_prompt)
    except Exception as e:
        verdict = {'action': 'HOLD', 'quantity': 0, 'confidence': 0.0, 'reasoning': f'Judge LLM error: {e}'}

    action = str(verdict.get('action', 'HOLD')).upper()
    if action not in ('BUY', 'SELL', 'HOLD'):
        action = 'HOLD'
    quantity = int(verdict.get('quantity', 0) or 0)
    confidence = float(verdict.get('confidence', 0.0) or 0.0)
    reasoning = str(verdict.get('reasoning', ''))

    # enforce risk
    price = ctx['price']
    if action == 'BUY' and price and price > 0:
        max_qty = int((cash * 0.20) / price)
        quantity = max(0, min(quantity, max_qty))
        if quantity == 0:
            action = 'HOLD'
            reasoning += ' [Capped: insufficient cash]'
    elif action == 'SELL':
        quantity = max(0, min(quantity, holdings_qty))

    transcript = (
        f"BULL ({agents['bull'].get('stance')}, {agents['bull'].get('confidence')}): {agents['bull'].get('reasoning')}\n\n"
        f"BEAR ({agents['bear'].get('stance')}, {agents['bear'].get('confidence')}): {agents['bear'].get('reasoning')}\n\n"
        f"RISK ({agents['risk'].get('stance')}, {agents['risk'].get('confidence')}): {agents['risk'].get('reasoning')}\n\n"
        f"JUDGE: {action} {quantity} (conf {confidence}) - {reasoning}"
    )

    row = AIDecision(
        user_id=user.id,
        symbol=symbol.upper(),
        action=action,
        quantity=quantity,
        confidence=confidence,
        reasoning=reasoning,
        model=model,
        executed=0,
        debate_transcript=transcript,
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
        'memory_available': mem_available(),
        'agents': agents,
        'transcript': transcript,
    }
