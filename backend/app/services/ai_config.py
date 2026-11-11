"""Runtime configuration for the AI trader, stored in app_state (DB)."""
from typing import Any, Dict
from sqlalchemy.orm import Session
from app.models.app_state import AppState

_KEYS = {
    'llm_base_url': 'LLM_BASE_URL',
    'llm_api_key': 'LLM_API_KEY',
    'llm_model': 'LLM_MODEL',
    'ai_enabled': 'AI_ENABLED',
    'ai_watchlist': 'AI_WATCHLIST',
    'ai_interval_minutes': 'AI_INTERVAL_MINUTES',
    'ai_max_trades_per_day': 'AI_MAX_TRADES_PER_DAY',
    'ai_cooldown_minutes': 'AI_COOLDOWN_MINUTES',
    'ai_min_confidence': 'AI_MIN_CONFIDENCE',
    'ai_dry_run': 'AI_DRY_RUN',
}


def _get(db: Session, key: str, default: str = '') -> str:
    row = db.query(AppState).filter(AppState.key == key).first()
    return row.value if row else default


def _set(db: Session, key: str, value: str):
    row = db.query(AppState).filter(AppState.key == key).first()
    if row:
        row.value = value
    else:
        db.add(AppState(key=key, value=value))


def get_llm_config(db: Session) -> Dict[str, str]:
    from app.config import settings
    return {
        'base_url': _get(db, 'llm_base_url', settings.LLM_BASE_URL),
        'api_key': _get(db, 'llm_api_key', settings.LLM_API_KEY),
        'model': _get(db, 'llm_model', settings.LLM_MODEL),
    }


def set_llm_config(db: Session, base_url: str, api_key: str, model: str):
    _set(db, 'llm_base_url', base_url)
    _set(db, 'llm_api_key', api_key)
    _set(db, 'llm_model', model)
    db.commit()


def get_ai_config(db: Session) -> Dict[str, Any]:
    from app.config import settings
    watchlist = _get(db, 'ai_watchlist', '')
    return {
        'enabled': _get(db, 'ai_enabled', 'false').lower() == 'true',
        'watchlist': [s.strip().upper() for s in watchlist.split(',') if s.strip()],
        'interval_minutes': int(_get(db, 'ai_interval_minutes', '15') or 15),
        'max_trades_per_day': int(_get(db, 'ai_max_trades_per_day', '5') or 5),
        'cooldown_minutes': int(_get(db, 'ai_cooldown_minutes', '30') or 30),
        'min_confidence': float(_get(db, 'ai_min_confidence', '0.6') or 0.6),
        'dry_run': _get(db, 'ai_dry_run', 'true').lower() == 'true',
    }


def set_ai_config(db: Session, cfg: Dict[str, Any]):
    _set(db, 'ai_enabled', 'true' if cfg.get('enabled') else 'false')
    _set(db, 'ai_watchlist', ','.join(cfg.get('watchlist', [])))
    _set(db, 'ai_interval_minutes', str(cfg.get('interval_minutes', 15)))
    _set(db, 'ai_max_trades_per_day', str(cfg.get('max_trades_per_day', 5)))
    _set(db, 'ai_cooldown_minutes', str(cfg.get('cooldown_minutes', 30)))
    _set(db, 'ai_min_confidence', str(cfg.get('min_confidence', 0.6)))
    _set(db, 'ai_dry_run', 'true' if cfg.get('dry_run') else 'false')
    db.commit()
