"""Build the portable Windows EXE.

1. Builds the React frontend into frontend/dist.
2. Packages the backend + frontend into dist/StockMarketSimulator.exe
   using StockMarketSimulator.spec.
"""

from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
FRONTEND = ROOT / 'frontend'
SPEC = ROOT / 'StockMarketSimulator.spec'


def run(command, cwd, shell=False):
    print('+', ' '.join(command), flush=True)
    subprocess.run(command, cwd=cwd, check=True, shell=shell)


if __name__ == '__main__':
    run(['npm', 'run', 'build'], FRONTEND, shell=(sys.platform == 'win32'))
    run(
        [sys.executable, '-m', 'PyInstaller', '--clean', '--noconfirm', str(SPEC)],
        ROOT,
    )
    print(f'Built: {ROOT / "dist" / "StockMarketSimulator.exe"}')
