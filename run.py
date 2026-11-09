import os
import sys
import threading
import time
import urllib.request

# Windowed mode: ensure stdout/stderr exist
if sys.stdout is None:
    sys.stdout = open(os.devnull, 'w')
if sys.stderr is None:
    sys.stderr = open(os.devnull, 'w')

# Ensure backend package importable
if getattr(sys, 'frozen', False):
    base = sys._MEIPASS
else:
    base = os.path.abspath(os.path.dirname(__file__))
backend_dir = os.path.join(base, 'backend')
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)
project_root = base
if project_root not in sys.path:
    sys.path.insert(0, project_root)

import uvicorn

_server_ready = threading.Event()

def run_server():
    uvicorn.run('app.main:app', host='127.0.0.1', port=8000, log_level='warning')

def wait_for_server():
    for _ in range(120):
        try:
            urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=1)
            _server_ready.set()
            return True
        except Exception:
            time.sleep(0.5)
    return False

if __name__ == '__main__':
    t = threading.Thread(target=run_server, daemon=True)
    t.start()
    wait_for_server()

    try:
        import webview
        webview.create_window(
            'Stock Market Simulator',
            'http://127.0.0.1:8000',
            width=1280,
            height=820,
            resizable=True,
            min_size=(900, 600),
        )
        webview.start()
    except Exception as e:
        # Fallback to default browser if native window is unavailable
        import webbrowser
        webbrowser.open('http://127.0.0.1:8000')
        # Keep server running
        while True:
            time.sleep(3600)