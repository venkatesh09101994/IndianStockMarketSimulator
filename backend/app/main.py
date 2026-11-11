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
from app.jobs.scheduler import start_scheduler, scheduler

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

    # Start background scheduler
    try:
        start_scheduler()
    except Exception as e:
        logger.warning(f'Scheduler could not be started: {e}')

    yield

    # Shutdown
    if scheduler.running:
        scheduler.shutdown(wait=False)
    logger.info('Backend shutdown completed.')

app = FastAPI(
    title='Indian Stock Market Simulator API',
    description='Paper trading engine for NSE with real market data, orders, portfolio & insights',
    version='1.0.0',
    lifespan=lifespan
)

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
        index_file = os.path.join(frontend_dist, 'index.html')
        if os.path.exists(index_file):
            return FileResponse(index_file)
        raise HTTPException(status_code=404, detail='Frontend not built')
