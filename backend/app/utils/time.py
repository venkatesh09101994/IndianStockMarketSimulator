from datetime import datetime, timezone
from typing import Optional


def to_utc(dt: Optional[datetime]) -> Optional[datetime]:
    """Normalize a datetime to a timezone-aware UTC value.

    SQLite stores datetimes without timezone information, so values read back
    from the database are naive. Those values were originally written in UTC,
    so we tag them as UTC instead of letting clients guess the timezone.
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
