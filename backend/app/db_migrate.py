"""Lightweight SQLite migrations for columns added after initial release."""
from sqlalchemy import inspect, text
from app.db import engine

_ADDITIONS = {
    'trades': [
        ('charges', 'BIGINT NOT NULL DEFAULT 0'),
    ],
    'ai_decisions': [
        ('dry_run', 'INTEGER NOT NULL DEFAULT 0'),
        ('scheduled', 'INTEGER NOT NULL DEFAULT 0'),
        ('guardrail_note', 'VARCHAR(255)'),
    ],
}


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
