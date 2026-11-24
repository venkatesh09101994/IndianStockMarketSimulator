import logging
import os
import socket
import sys
import threading
import time
import urllib.request

FROZEN = getattr(sys, 'frozen', False)
LAUNCH_DIR = os.path.dirname(sys.executable) if FROZEN else os.path.abspath(os.path.dirname(__file__))

# In windowed mode stdout/stderr do not exist. Keep them valid for libraries
# that write to them, and mirror diagnostics to a log next to the EXE.
if FROZEN:
    logging.basicConfig(
        filename=os.path.join(LAUNCH_DIR, 'startup.log'),
        filemode='w',
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    )
if sys.stdout is None:
    sys.stdout = open(os.devnull, 'w')
if sys.stderr is None:
    sys.stderr = open(os.devnull, 'w')

logger = logging.getLogger('stock-sim-launcher')

# Ensure backend package importable
if FROZEN:
    base = getattr(sys, '_MEIPASS', LAUNCH_DIR)
else:
    base = os.path.abspath(os.path.dirname(__file__))
backend_dir = os.path.join(base, 'backend')
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)
project_root = base
if project_root not in sys.path:
    sys.path.insert(0, project_root)

try:
    # Import the ASGI app directly so PyInstaller can see every backend
    # module at analysis time. uvicorn's string import is not detectable.
    from app.main import app as fastapi_app
except Exception:
    logger.exception('Failed to import backend application')
    raise

import uvicorn

_server_ready = threading.Event()
SERVER_PORT = 8000
APP_URL = 'http://127.0.0.1:8000'


def _choose_port(preferred: int = 8000) -> int:
    """Use the preferred port when free, otherwise pick an available one."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind(('127.0.0.1', preferred))
            return preferred
        except OSError:
            pass

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(('127.0.0.1', 0))
        return probe.getsockname()[1]


def run_server():
    try:
        uvicorn.run(fastapi_app, host='127.0.0.1', port=SERVER_PORT, log_level='warning')
    except Exception:
        logger.exception('Backend server stopped unexpectedly')


def wait_for_server():
    for _ in range(120):
        try:
            with urllib.request.urlopen(APP_URL + '/health', timeout=1) as response:
                if response.status == 200:
                    _server_ready.set()
                    return True
        except Exception:
            pass
        time.sleep(0.5)
    return False


if __name__ == '__main__':
    SERVER_PORT = _choose_port(8000)
    APP_URL = f'http://127.0.0.1:{SERVER_PORT}'
    logger.info('Starting backend at %s', APP_URL)

    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()

    if not wait_for_server():
        logger.error('Backend did not become ready at %s', APP_URL)
        raise RuntimeError(f'Backend did not become ready at {APP_URL}')

    try:
        import webview
        webview.create_window(
            'Stock Market Simulator',
            APP_URL,
            width=1280,
            height=820,
            resizable=True,
            maximized=True,
            min_size=(900, 600),
        )
        webview.start()
    except Exception:
        logger.exception('Native window unavailable; opening the default browser')
        import webbrowser
        webbrowser.open(APP_URL)
        # Keep server running so the browser can use the app.
        while True:
            time.sleep(3600)
