"""
Shared helpers for persistent key-value sync state and outbound URL validation.
Previously these were duplicated across services/integrations.py, services/sync_jobs.py
and services/drift.py.
"""
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import SyncState


# ---------------------------------------------------------------------------
# Sync state (key-value store in DB)
# ---------------------------------------------------------------------------

def read_sync_state(db: Session, key: str) -> str | None:
    """Read a persisted sync-state value by key. Returns None if absent."""
    state = db.get(SyncState, key)
    return state.value if state else None


def write_sync_state(db: Session, key: str, value: str) -> None:
    """Upsert a persisted sync-state value."""
    state = db.get(SyncState, key)
    if state is None:
        db.add(SyncState(key=key, value=value))
        return
    state.value = value


# ---------------------------------------------------------------------------
# Outbound URL validation
# ---------------------------------------------------------------------------

def is_non_dev_environment() -> bool:
    """Return True when running in a non-development environment."""
    settings = get_settings()
    return settings.app_env.strip().lower() not in {"dev", "development", "local", "test"}


def validated_outbound_url(url: str, target: str) -> str:
    """
    Validate and return a sanitised outbound URL.

    Raises ValueError with a slug-style reason if the URL is invalid or if
    HTTP (non-TLS) is used in a production environment.
    """
    value = url.strip()
    if not value:
        return ""
    parsed = urlparse(value)
    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"{target}_url_invalid")
    if is_non_dev_environment() and scheme != "https":
        raise ValueError(f"{target}_url_requires_https")
    return value


def valid_base_url(value: str) -> str:
    """
    Return the URL stripped of trailing slash if it passes validation,
    or an empty string if it is blank/invalid.

    Does NOT raise — callers that need strict enforcement should use
    `validated_outbound_url` directly.
    """
    base = value.strip().rstrip("/")
    if not base:
        return ""
    try:
        validated_outbound_url(base, "generic")
    except ValueError:
        return ""
    return base
