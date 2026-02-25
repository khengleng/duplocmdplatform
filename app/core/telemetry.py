import threading
import time
from collections import defaultdict, deque
from typing import Any

from app.core.time import utcnow

WINDOW_SECONDS = 300

_lock = threading.Lock()
_events: dict[str, deque[float]] = defaultdict(deque)

_ALERT_RULES: list[dict[str, Any]] = [
    {
        "id": "rate-limit-spike",
        "event": "api.rate_limited",
        "threshold": 20,
        "severity": "warning",
        "message": "High number of rate-limited requests in the last 5 minutes.",
    },
    {
        "id": "server-error-spike",
        "event": "api.server_error",
        "threshold": 5,
        "severity": "critical",
        "message": "High number of server-side errors in the last 5 minutes.",
    },
    {
        "id": "sync-job-failures",
        "event": "sync.job_failed",
        "threshold": 3,
        "severity": "critical",
        "message": "Multiple sync jobs failed in the last 5 minutes.",
    },
]


def _prune(queue: deque[float], cutoff: float) -> None:
    while queue and queue[0] < cutoff:
        queue.popleft()


def record_event(event_type: str) -> None:
    now = time.monotonic()
    cutoff = now - WINDOW_SECONDS
    with _lock:
        queue = _events[event_type]
        _prune(queue, cutoff)
        queue.append(now)


def _current_counts() -> dict[str, int]:
    now = time.monotonic()
    cutoff = now - WINDOW_SECONDS
    tracked = {rule["event"] for rule in _ALERT_RULES}
    counts: dict[str, int] = {}
    with _lock:
        for event_type in tracked.union(_events.keys()):
            queue = _events[event_type]
            _prune(queue, cutoff)
            counts[event_type] = len(queue)
    return counts


def get_alert_snapshot() -> dict[str, Any]:
    counts = _current_counts()
    rules: list[dict[str, Any]] = []
    active_alerts: list[dict[str, Any]] = []

    for rule in _ALERT_RULES:
        current_value = counts.get(rule["event"], 0)
        alert = {
            "id": rule["id"],
            "event": rule["event"],
            "threshold": rule["threshold"],
            "current": current_value,
            "severity": rule["severity"],
            "message": rule["message"],
            "active": current_value >= int(rule["threshold"]),
        }
        rules.append(alert)
        if alert["active"]:
            active_alerts.append(alert)

    return {
        "generated_at": utcnow().isoformat(),
        "window_seconds": WINDOW_SECONDS,
        "counts": counts,
        "rules": rules,
        "active_alerts": active_alerts,
    }
