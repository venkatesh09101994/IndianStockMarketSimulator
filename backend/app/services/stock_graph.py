import os
import json
import logging
from typing import Dict, List, Any, Optional
from sqlalchemy.orm import Session
from app.models.stock import Stock, PriceHistory
from app.models.holding import Holding

logger = logging.getLogger(__name__)

def _data_dir() -> str:
    if os.path.exists('/app'):
        return '/app/data'
    base = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
    d = os.path.join(base, 'data')
    os.makedirs(d, exist_ok=True)
    return d

GRAPH_PATH = os.path.join(_data_dir(), 'stock_graph.json')

def build_graph(db: Session) -> Dict[str, Any]:
    stocks = db.query(Stock).filter(Stock.is_active == True).all()
    nodes = []
    edges = []
    # sector communities
    sectors: Dict[str, List[str]] = {}
    for s in stocks:
        nodes.append({'id': s.symbol, 'label': s.company_name, 'sector': s.sector, 'group': s.sector})
        sectors.setdefault(s.sector or 'Unknown', []).append(s.symbol)

    # edges: same sector (star topology to reduce density)
    for sector, syms in sectors.items():
        if len(syms) <= 1:
            continue
        hub = syms[0]
        for s in syms[1:]:
            edges.append({'source': hub, 'target': s, 'relation': 'same_sector', 'weight': 0.3})

    # price correlation edges (top correlated pairs)
    # build price series per symbol
    series: Dict[str, List[float]] = {}
    for s in stocks:
        hist = db.query(PriceHistory).filter(PriceHistory.stock_id == s.id, PriceHistory.interval == '1d').order_by(PriceHistory.ts).limit(30).all()
        if len(hist) >= 5:
            series[s.symbol] = [h.close / 100.0 for h in hist]

    # compute correlation for pairs; keep only top-3 per node to avoid dense hairball
    syms_list = list(series.keys())
    corr_candidates = []
    for i in range(len(syms_list)):
        for j in range(i + 1, len(syms_list)):
            a, b = syms_list[i], syms_list[j]
            sa, sb = series[a], series[b]
            n = min(len(sa), len(sb))
            if n < 5:
                continue
            sa, sb = sa[-n:], sb[-n:]
            import statistics
            try:
                ma, mb = statistics.mean(sa), statistics.mean(sb)
                va = [x - ma for x in sa]
                vb = [x - mb for x in sb]
                num = sum(x * y for x, y in zip(va, vb))
                da = (sum(x * x for x in va)) ** 0.5
                db_ = (sum(x * x for x in vb)) ** 0.5
                if da == 0 or db_ == 0:
                    continue
                corr = num / (da * db_)
            except Exception:
                continue
            if abs(corr) >= 0.9:
                corr_candidates.append((a, b, round(abs(corr), 2)))
    # keep top-3 per node
    from collections import defaultdict
    per_node = defaultdict(list)
    for a, b, w in corr_candidates:
        per_node[a].append((b, w))
        per_node[b].append((a, w))
    kept = set()
    for node, lst in per_node.items():
        lst.sort(key=lambda x: -x[1])
        for b, w in lst[:3]:
            key = tuple(sorted((node, b)))
            if key not in kept:
                kept.add(key)
                edges.append({'source': node, 'target': b, 'relation': 'correlated', 'weight': w})

    graph = {
        'nodes': nodes,
        'edges': edges,
        'communities': {k: v for k, v in sectors.items()},
        'node_count': len(nodes),
        'edge_count': len(edges),
    }
    try:
        os.makedirs(_data_dir(), exist_ok=True)
        with open(GRAPH_PATH, 'w') as f:
            json.dump(graph, f)
    except Exception as e:
        logger.warning(f'Failed to save graph: {e}')
    return graph

def load_graph() -> Optional[Dict[str, Any]]:
    if not os.path.exists(GRAPH_PATH):
        return None
    try:
        with open(GRAPH_PATH) as f:
            return json.load(f)
    except Exception:
        return None

def neighbors(symbol: str, graph: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    g = graph or load_graph()
    if not g:
        return []
    sym = symbol.upper()
    related = []
    for e in g.get('edges', []):
        if e['source'] == sym:
            related.append({'symbol': e['target'], 'relation': e['relation'], 'weight': e.get('weight', 0)})
        elif e['target'] == sym:
            related.append({'symbol': e['source'], 'relation': e['relation'], 'weight': e.get('weight', 0)})
    # dedupe
    seen = set()
    out = []
    for r in related:
        if r['symbol'] in seen:
            continue
        seen.add(r['symbol'])
        out.append(r)
    return out[:15]

def sector_peers(symbol: str, graph: Optional[Dict[str, Any]] = None) -> List[str]:
    g = graph or load_graph()
    if not g:
        return []
    for n in g.get('nodes', []):
        if n['id'] == symbol.upper():
            sector = n.get('sector')
            return [x['id'] for x in g['nodes'] if x.get('sector') == sector and x['id'] != symbol.upper()][:8]
    return []