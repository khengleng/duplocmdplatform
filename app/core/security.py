import hashlib
import secrets
import threading
import time
from collections import defaultdict, deque

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import get_settings

bearer_scheme = HTTPBearer(auto_error=False)


class SlidingWindowLimiter:
    def __init__(self, max_requests: int, window_seconds: int) -> None:
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        cutoff = now - self.window_seconds
        with self._lock:
            queue = self._events[key]
            while queue and queue[0] < cutoff:
                queue.popleft()
            if len(queue) >= self.max_requests:
                return False
            queue.append(now)
            return True


_rate_limiter: SlidingWindowLimiter | None = None
_global_rate_limiter: SlidingWindowLimiter | None = None


def _get_rate_limiter() -> SlidingWindowLimiter:
    global _rate_limiter
    settings = get_settings()
    max_requests = max(1, settings.mutating_rate_limit_per_minute)
    if _rate_limiter is None or _rate_limiter.max_requests != max_requests:
        _rate_limiter = SlidingWindowLimiter(
            max_requests=max_requests,
            window_seconds=60,
        )
    return _rate_limiter


def _get_global_rate_limiter() -> SlidingWindowLimiter:
    global _global_rate_limiter
    settings = get_settings()
    max_requests = max(1, settings.global_rate_limit_per_minute)
    if _global_rate_limiter is None or _global_rate_limiter.max_requests != max_requests:
        _global_rate_limiter = SlidingWindowLimiter(
            max_requests=max_requests,
            window_seconds=60,
        )
    return _global_rate_limiter


def global_rate_limit_key(request: Request) -> str:
    auth_header = request.headers.get("authorization", "")
    token_fingerprint = ""
    if auth_header.lower().startswith("bearer "):
        token = auth_header[7:].strip()
        if token:
            token_fingerprint = hashlib.sha256(token.encode("utf-8")).hexdigest()[:12]

    if token_fingerprint:
        return f"token:{token_fingerprint}:{request.url.path}"

    client_host = request.client.host if request.client else "unknown"
    return f"ip:{client_host}:{request.url.path}"


def enforce_global_rate_limit(request: Request) -> bool:
    limiter = _get_global_rate_limiter()
    return limiter.allow(global_rate_limit_key(request))


def require_service_auth(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> str:
    settings = get_settings()
    legacy_operator_tokens = [token.strip() for token in settings.service_auth_tokens.split(",") if token.strip()]
    explicit_operator_tokens = [token.strip() for token in settings.service_operator_tokens.split(",") if token.strip()]
    viewer_tokens = [token.strip() for token in settings.service_viewer_tokens.split(",") if token.strip()]

    operator_tokens = legacy_operator_tokens + explicit_operator_tokens

    if not operator_tokens and not viewer_tokens:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Service authentication is not configured",
        )

    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials.strip()
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    for expected in operator_tokens:
        if secrets.compare_digest(token, expected):
            principal_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()[:12]
            request.state.service_principal = f"service:{principal_hash}"
            request.state.service_scope = "operator"
            return token

    for expected in viewer_tokens:
        if secrets.compare_digest(token, expected):
            principal_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()[:12]
            request.state.service_principal = f"service:{principal_hash}"
            request.state.service_scope = "viewer"
            return token

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Invalid service token",
    )


def require_operator_scope(request: Request) -> None:
    scope = getattr(request.state, "service_scope", None)
    if scope != "operator":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Operator scope required",
        )


def require_mutation_rate_limit(request: Request) -> None:
    require_operator_scope(request)
    limiter = _get_rate_limiter()
    principal = getattr(request.state, "service_principal", "service:unknown")
    route_key = request.url.path
    key = f"{principal}:{route_key}"
    if not limiter.allow(key):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded for mutating endpoint",
        )
