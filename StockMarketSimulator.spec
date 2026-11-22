# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the portable Stock Market Simulator build.

Bundles the FastAPI backend, the built React frontend, seed data and the
pywebview runtime into a single EXE. Run with:

    python -m PyInstaller --clean --noconfirm StockMarketSimulator.spec
"""

from pathlib import Path

try:
    from PyInstaller.utils.hooks import collect_data_files
except ImportError:  # pragma: no cover - PyInstaller is required to build
    collect_data_files = None

ROOT = Path(SPECPATH)
BACKEND = ROOT / 'backend'
APP = BACKEND / 'app'
FRONTEND_DIST = ROOT / 'frontend' / 'dist'
ENV_FILE = ROOT / '.env'


def add_tree(source: Path, destination: Path, target):
    """Add every regular file below source, preserving its relative path."""
    if not source.exists():
        return
    for item in source.rglob('*'):
        if not item.is_file() or '__pycache__' in item.parts:
            continue
        relative = item.relative_to(source)
        target.append((str(item), str(destination / relative.parent)))


datas = []
add_tree(APP, Path('backend') / 'app', datas)          # filesystem fallback
add_tree(APP, Path('app'), datas)                      # compiled-module resources
add_tree(FRONTEND_DIST, Path('frontend') / 'dist', datas)

if ENV_FILE.exists():
    datas.append((str(ENV_FILE), '.'))

if collect_data_files is not None:
    for package in ('webview', 'certifi', 'tzdata'):
        try:
            datas.extend(collect_data_files(package))
        except Exception:
            pass

# Deduplicate datas entries while preserving order.
seen = set()
datas = [entry for entry in datas if not (entry in seen or seen.add(entry))]

hiddenimports = []
for py_file in APP.rglob('*.py'):
    if '__pycache__' in py_file.parts:
        continue
    parts = list(py_file.relative_to(BACKEND).with_suffix('').parts)
    if parts and parts[-1] == '__init__':
        parts.pop()
    if parts:
        module = '.'.join(parts)
        if module not in hiddenimports:
            hiddenimports.append(module)

hiddenimports.extend([
    'uvicorn',
    'uvicorn.logging',
    'uvicorn.loops.auto',
    'uvicorn.protocols.http.auto',
    'uvicorn.protocols.websockets.auto',
    'uvicorn.lifespan.on',
    'anyio',
    'anyio._backends._asyncio',
    'webview',
    'webview.platforms.winforms',
    'webview.platforms.edgechromium',
    'apscheduler.schedulers.background',
    'apscheduler.triggers.interval',
    'apscheduler.triggers.cron',
    'yfinance',
    'tzdata',
])

hiddenimports = list(dict.fromkeys(hiddenimports))


a = Analysis(
    ['run.py'],
    pathex=[str(ROOT), str(BACKEND)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'matplotlib',
        'tkinter',
        'pytest',
        'IPython',
        'notebook',
        'PyQt5',
        'PySide2',
    ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='StockMarketSimulator',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
