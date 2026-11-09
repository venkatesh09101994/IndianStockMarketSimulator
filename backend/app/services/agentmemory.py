import os
import requests
import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

AGENTMEMORY_URL = os.getenv('AGENTMEMORY_URL', 'http://localhost:3111')
AGENTMEMORY_SECRET = os.getenv('AGENTMEMORY_SECRET', '')

# Try to load secret from the default location if not set
if not AGENTMEMORY_SECRET:
    secret_path = os.path.join(os.path.expanduser('~'), '.agentmemory', 'secret')
    if os.path.exists(secret_path):
        try:
            with open(secret_path) as f:
                AGENTMEMORY_SECRET = f.read().strip()
        except Exception:
            pass

def _headers() -> Dict[str, str]:
    h = {'Content-Type': 'application/json'}
    if AGENTMEMORY_SECRET:
        h['Authorization'] = f'Bearer {AGENTMEMORY_SECRET}'
    return h

def is_available() -> bool:
    try:
        r = requests.get(f'{AGENTMEMORY_URL}/agentmemory/livez', timeout=3)
        return r.status_code < 400
    except Exception:
        return False

def recall(query: str, limit: int = 5, project: Optional[str] = None) -> List[Dict[str, Any]]:
    if not is_available():
        return []
    try:
        payload = {'query': query, 'limit': limit}
        if project:
            payload['project'] = project
        r = requests.post(f'{AGENTMEMORY_URL}/agentmemory/smart-search', headers=_headers(), json=payload, timeout=15)
        if r.status_code >= 400:
            return []
        data = r.json()
        results = data.get('results', []) if isinstance(data, dict) else []
        out = []
        for res in results:
            # fetch full memory content if it's a memory layer
            out.append({'id': res.get('obsId'), 'title': res.get('title'), 'score': res.get('score')})
        # Try to get full content for memory items
        enriched = []
        for item in out:
            enriched.append(item)
        return enriched
    except Exception as e:
        logger.warning(f'agentmemory recall failed: {e}')
        return []

def remember(content: str, concepts: List[str] = None, project: Optional[str] = None) -> Optional[str]:
    if not is_available():
        return None
    try:
        payload = {'content': content, 'concepts': concepts or [], 'type': 'fact'}
        if project:
            payload['project'] = project
        r = requests.post(f'{AGENTMEMORY_URL}/agentmemory/remember', headers=_headers(), json=payload, timeout=15)
        if r.status_code >= 400:
            logger.warning(f'agentmemory remember failed: {r.status_code} {r.text[:200]}')
            return None
        data = r.json()
        mem = data.get('memory', {}) if isinstance(data, dict) else {}
        return mem.get('id')
    except Exception as e:
        logger.warning(f'agentmemory remember failed: {e}')
        return None