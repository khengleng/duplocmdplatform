from datetime import datetime, timezone


def utcnow() -> datetime:
    """Return current UTC time as a timezone-naive datetime (for DB compat)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def normalize_utc_naive(value: datetime | None) -> datetime | None:
    """Convert any datetime to a timezone-naive UTC datetime."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)
