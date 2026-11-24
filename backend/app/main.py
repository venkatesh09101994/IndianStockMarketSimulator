import logging
from contextlib import asynccontextmanager
import os
import sys
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from app.config import settings
from app.db import engine, Base, SessionLocal
from app.db_migrate import run_migrations
from app.api import api_router
from app.seed.seeder import seed_database
from app.jobs.scheduler import start_scheduler, scheduler, job_refresh_quotes

def get_frontend_dist() -> str:
    # PyInstaller bundle
    if getattr(sys, 'frozen', False):
        base = sys._MEIPASS
    else:
        base = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
    return os.path.join(base, 'frontend', 'dist')

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(name)s: %(message)s')
logger = logging.getLogger('stock-sim')

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info('Initializing Indian Stock Market Simulator Backend...')
    # Create DB tables
    Base.metadata.create_all(bind=engine)
    # Lightweight migrations for older DBs
    try:
        run_migrations()
    except Exception as e:
        logger.warning(f'Migration step failed: {e}')

    # Seed database
    db = SessionLocal()
    try:
        seed_database(db)
    finally:
        db.close()

    # Refresh quotes immediately on every launch so the UI never opens with a
    # stale timestamp or stale portfolio valuations.
    try:
        job_refresh_quotes()
    except Exception as e:
        logger.warning(f'Initial quote refresh failed: {e}')

    # Start background scheduler
    try:
        start_scheduler()
    except Exception as e:
        logger.warning(f'Scheduler could not be started: {e}')

    # Startup catch-up: close stale MIS positions from days the app was closed
    try:
        from app.services.square_off import close_stale_mis_positions
        _db = SessionLocal()
        try:
            close_stale_mis_positions(_db)
        finally:
            _db.close()
    except Exception as e:
        logger.warning(f'Stale MIS cleanup failed: {e}')

    # Startup catch-up: expire DAY/GTT orders that missed their deadline while
    # the process was not running, releasing any blocked cash.
    try:
        from app.services.order_service import expire_pending_orders
        _db = SessionLocal()
        try:
            expired = expire_pending_orders(_db)
            if expired:
                logger.info('Expired %d stale pending order(s) on startup', expired)
        finally:
            _db.close()
    except Exception as e:
        logger.warning(f'Order expiry catch-up failed: {e}')

    if not settings.ALLOW_ANONYMOUS and settings.JWT_SECRET == 'stock-sim-jwt-secret-key-3289047239084723':
        logger.warning(
            'Authentication is required (ALLOW_ANONYMOUS=false) but JWT_SECRET '
            'is still the built-in default. Set a unique JWT_SECRET in .env.'
        )

    yield

    # Shutdown
    if scheduler.running:
        scheduler.shutdown(wait=False)
    logger.info('Backend shutdown completed.')

app = FastAPI(
    title='Indian Stock Market Simulator API',
    description='Paper trading engine for NSE with real market data, orders, portfolio & insights',
    version='1.1.0',
    lifespan=lifespan
)

@app.middleware('http')
async def add_security_headers(request, call_next):
    response = await call_next(request)
    response.headers.setdefault('X-Content-Type-Options', 'nosniff')
    response.headers.setdefault('X-Frame-Options', 'DENY')
    response.headers.setdefault('Referrer-Policy', 'strict-origin-when-cross-origin')
    response.headers.setdefault('Permissions-Policy', 'geolocation=(), microphone=(), camera=()')
    return response

# Setup CORS
allowed_origins = [o.strip() for o in settings.ALLOWED_ORIGINS.split(',') if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins or ['*'],
    allow_credentials=True,
    allow_methods=['*'],
    allow_headers=['*'],
)

# Include all API routes under /api
app.include_router(api_router, prefix='/api')

frontend_dist = get_frontend_dist()

@app.get('/health')
def health():
    return {'status': 'healthy'}

# Serve frontend (production / packaged build)
if os.path.isdir(frontend_dist):
    assets_dir = os.path.join(frontend_dist, 'assets')
    if os.path.isdir(assets_dir):
        app.mount('/assets', StaticFiles(directory=assets_dir), name='assets')

    @app.get('/{full_path:path}')
    def spa_fallback(full_path: str):
        # API and docs are handled above; serve index.html for client routes
        if full_path.startswith('api/') or full_path.startswith('docs') or full_path.startswith('openapi'):
            raise HTTPException(status_code=404, detail='Not found')

        # Serve real files from the build (favicon.svg, bse-bull.jpg, icons.svg,
        # ...) instead of returning index.html for every asset request.
        if full_path:
            candidate = os.path.abspath(os.path.join(frontend_dist, full_path))
            root = os.path.abspath(frontend_dist)
            try:
                inside_build = os.path.commonpath([candidate, root]) == root
            except ValueError:
                inside_build = False
            if inside_build and os.path.isfile(candidate):
                return FileResponse(candidate)

        index_file = os.path.join(frontend_dist, 'index.html')
        if os.path.exists(index_file):
            return FileResponse(index_file)
        raise HTTPException(status_code=404, detail='Frontend not built')
