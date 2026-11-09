from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.api.deps import get_db, get_current_user
from app.models.user import User
from app.services.stock_graph import build_graph, load_graph, neighbors, sector_peers

router = APIRouter(prefix='/graph', tags=['Knowledge Graph'])

@router.post('/build')
def build(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    g = build_graph(db)
    return {'nodes': g['node_count'], 'edges': g['edge_count'], 'communities': len(g['communities'])}

@router.get('/stats')
def stats(db: Session = Depends(get_db)):
    g = load_graph()
    if not g:
        g = build_graph(db)
    return {'nodes': g['node_count'], 'edges': g['edge_count'], 'communities': len(g['communities']), 'sectors': list(g['communities'].keys())}

@router.get('/neighbors/{symbol}')
def get_neighbors(symbol: str, db: Session = Depends(get_db)):
    g = load_graph()
    if not g:
        g = build_graph(db)
    return {'symbol': symbol.upper(), 'neighbors': neighbors(symbol, g), 'peers': sector_peers(symbol, g)}

@router.get('/full')
def full(db: Session = Depends(get_db)):
    g = load_graph()
    if not g:
        g = build_graph(db)
    return g