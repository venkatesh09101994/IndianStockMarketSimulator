"""Lightweight SQLite migrations for columns added after initial release."""
import logging
from sqlalchemy import inspect, text
from app.db import engine

logger = logging.getLogger(__name__)

_ADDITIONS = {
    'accounts': [
        ('realized_pnl_total', 'BIGINT NOT NULL DEFAULT 0'),
    ],
    'trades': [
        ('charges', 'BIGINT NOT NULL DEFAULT 0'),
    ],
    'orders': [
        ('reject_reason', 'VARCHAR(255)'),
        ('expires_at', 'DATETIME'),
        ('placed_price', 'BIGINT'),
        ('placed_day_high', 'BIGINT'),
        ('placed_day_low', 'BIGINT'),
    ],
    'positions': [
        ('closed_at', 'DATETIME'),
    ],
    'portfolio_snapshots': [
        ('realized_pnl_total', 'BIGINT NOT NULL DEFAULT 0'),
    ],
    'latest_quotes': [
        ('return_1m_pct', 'FLOAT DEFAULT 0'),
        ('return_6m_pct', 'FLOAT DEFAULT 0'),
        ('return_1y_pct', 'FLOAT DEFAULT 0'),
        ('avg_volume_20d', 'BIGINT DEFAULT 0'),
    ],
    'ai_decisions': [
        ('dry_run', 'INTEGER NOT NULL DEFAULT 0'),
        ('scheduled', 'INTEGER NOT NULL DEFAULT 0'),
        ('guardrail_note', 'VARCHAR(255)'),
        ('debate_transcript', 'TEXT'),
        ('was_correct', 'INTEGER'),
        ('outcome_pnl', 'BIGINT'),
    ],
}

# One trade per order is an invariant of the execution engine. Enforce it on
# existing databases as well as new ones so a double fill cannot be persisted.
_UNIQUE_INDEXES = [
    ('trades', 'CREATE UNIQUE INDEX IF NOT EXISTS uix_trades_order_id ON trades(order_id)'),
]


def run_migrations():
    insp = inspect(engine)
    existing_tables = set(insp.get_table_names())
    with engine.begin() as conn:
        for table, cols in _ADDITIONS.items():
            if table not in existing_tables:
                continue
            existing_cols = {c['name'] for c in insp.get_columns(table)}
            for col_name, col_type in cols:
                if col_name in existing_cols:
                    continue
                conn.execute(text(f'ALTER TABLE {table} ADD COLUMN {col_name} {col_type}'))

        for table, statement in _UNIQUE_INDEXES:
            if table not in existing_tables:
                continue
            try:
                conn.execute(text(statement))
            except Exception as e:
                # A database that already contains duplicate trades cannot be
                # migrated automatically; log it and let the app start.
                logger.warning(f'Could not create unique index on {table}: {e}')
