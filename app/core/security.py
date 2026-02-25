import hashlib
import json
import secrets
import threading
import time
from collections import defaultdict, deque

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import InvalidTokenError, PyJWKClient, PyJWKClientError, decode
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.core.time import utcnow
from app.models import ApprovalStatus, ChangeApproval

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


_rate_limiters: dict[int, SlidingWindowLimiter] = {}
_rate_limiter_lock = threading.Lock()
_global_rate_limiter: SlidingWindowLimiter | None = None
_jwks_client: tuple[str, PyJWKClient] | None = None
_jwks_lock = threading.Lock()


def _get_rate_limiter(max_requests: int) -> SlidingWindowLimiter:
    limit = max(1, max_requests)
    with _rate_limiter_lock:
        limiter = _rate_limiters.get(limit)
        if limiter is None:
            limiter = SlidingWindowLimiter(
                max_requests=limit,
                window_seconds=60,
            )
            _rate_limiters[limit] = limiter
        return limiter


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


def _split_tokens(raw: str) -> list[str]:
    return [token.strip() for token in raw.split(",") if token.strip()]


def canonical_request_path(request: Request) -> str:
    query = request.url.query
    return f"{request.url.path}?{query}" if query else request.url.path


def _normalize_json_bytes(payload: object) -> bytes:
    return json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")


def canonical_payload_hash(body_bytes: bytes, content_type: str | None = None) -> str:
    payload = body_bytes
    content_type_value = (content_type or "").lower()
    if body_bytes and "application/json" in content_type_value:
        try:
            payload = _normalize_json_bytes(json.loads(body_bytes.decode("utf-8")))
        except (ValueError, UnicodeDecodeError):
            payload = body_bytes
    return hashlib.sha256(payload).hexdigest()


def canonical_payload_hash_from_object(payload: object) -> str:
    if payload is None:
        return hashlib.sha256(b"").hexdigest()
    return hashlib.sha256(_normalize_json_bytes(payload)).hexdigest()


def _mutation_rate_limit_for_path(path: str, *, approver: bool = False) -> int:
    settings = get_settings()
    if approver:
        return max(1, settings.approver_mutating_rate_limit_per_minute)
    if path.startswith("/ingest"):
        return max(1, settings.mutating_rate_limit_ingest_per_minute)
    if path.startswith("/integrations"):
        return max(1, settings.mutating_rate_limit_integrations_per_minute)
    if path.startswith("/relationships"):
        return max(1, settings.mutating_rate_limit_relationships_per_minute)
    if path.startswith("/cis"):
        return max(1, settings.mutating_rate_limit_cis_per_minute)
    if path.startswith("/governance"):
        return max(1, settings.mutating_rate_limit_governance_per_minute)
    if path.startswith("/lifecycle"):
        return max(1, settings.mutating_rate_limit_lifecycle_per_minute)
    if path.startswith("/approvals"):
        return max(1, settings.mutating_rate_limit_approvals_per_minute)
    return max(1, settings.mutating_rate_limit_per_minute)


def _mutation_payload_limit_for_path(path: str) -> int:
    settings = get_settings()
    if path.startswith("/ingest"):
        return max(1, settings.mutating_payload_limit_ingest_bytes)
    if path.startswith("/integrations"):
        return max(1, settings.mutating_payload_limit_integrations_bytes)
    if path.startswith("/relationships"):
        return max(1, settings.mutating_payload_limit_relationships_bytes)
    if path.startswith("/cis"):
        return max(1, settings.mutating_payload_limit_cis_bytes)
    if path.startswith("/governance"):
        return max(1, settings.mutating_payload_limit_governance_bytes)
    if path.startswith("/lifecycle"):
        return max(1, settings.mutating_payload_limit_lifecycle_bytes)
    if path.startswith("/approvals"):
        return max(1, settings.mutating_payload_limit_approvals_bytes)
    return max(1, settings.mutating_payload_limit_default_bytes)


def _enforce_mutation_payload_limit(request: Request) -> None:
    content_length = request.headers.get("content-length")
    if content_length is None:
        return
    try:
        declared_size = int(content_length)
    except ValueError:
        return
    limit_bytes = _mutation_payload_limit_for_path(request.url.path)
    if declared_size > limit_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Request payload exceeds endpoint limit ({limit_bytes} bytes)",
        )


def _apply_mutation_rate_limit(request: Request, *, approver: bool = False) -> None:
    max_requests = _mutation_rate_limit_for_path(request.url.path, approver=approver)
    limiter = _get_rate_limiter(max_requests)
    principal = getattr(request.state, "service_principal", "service:unknown")
    route_key = request.url.path
    key = f"{principal}:{route_key}"
    if not limiter.allow(key):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded for mutating endpoint",
        )


def _get_jwks_client() -> PyJWKClient:
    global _jwks_client
    settings = get_settings()
    jwks_url = settings.oidc_jwks_url.strip()
    if not jwks_url:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="OIDC JWKS URL is not configured",
        )
    with _jwks_lock:
        if _jwks_client is None or _jwks_client[0] != jwks_url:
            _jwks_client = (jwks_url, PyJWKClient(jwks_url))
        return _jwks_client[1]


def _extract_oidc_scopes(claims: dict) -> set[str]:
    scopes: set[str] = set()

    scope_claim = claims.get("scope")
    if isinstance(scope_claim, str):
        scopes.update(scope_claim.split())

    scp_claim = claims.get("scp")
    if isinstance(scp_claim, str):
        scopes.update(scp_claim.split())
    elif isinstance(scp_claim, list):
        scopes.update(str(item) for item in scp_claim if item)

    roles_claim = claims.get("roles")
    if isinstance(roles_claim, list):
        scopes.update(str(item) for item in roles_claim if item)

    realm_access = claims.get("realm_access")
    if isinstance(realm_access, dict):
        realm_roles = realm_access.get("roles")
        if isinstance(realm_roles, list):
            scopes.update(str(item) for item in realm_roles if item)

    return scopes


def _try_static_token_auth(request: Request, token: str) -> bool:
    settings = get_settings()
    legacy_operator_tokens = _split_tokens(settings.service_auth_tokens)
    explicit_operator_tokens = _split_tokens(settings.service_operator_tokens)
    operator_tokens = legacy_operator_tokens + explicit_operator_tokens
    viewer_tokens = _split_tokens(settings.service_viewer_tokens)
    approver_tokens = _split_tokens(settings.service_approver_tokens)

    for expected in operator_tokens:
        if secrets.compare_digest(token, expected):
            principal_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()[:12]
            request.state.service_principal = f"service:{principal_hash}"
            request.state.service_scope = "operator"
            request.state.service_auth_source = "static"
            return True

    for expected in approver_tokens:
        if secrets.compare_digest(token, expected):
            principal_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()[:12]
            request.state.service_principal = f"service:{principal_hash}"
            request.state.service_scope = "approver"
            request.state.service_auth_source = "static"
            return True

    for expected in viewer_tokens:
        if secrets.compare_digest(token, expected):
            principal_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()[:12]
            request.state.service_principal = f"service:{principal_hash}"
            request.state.service_scope = "viewer"
            request.state.service_auth_source = "static"
            return True

    return False


def _try_oidc_auth(request: Request, token: str) -> bool:
    settings = get_settings()
    algorithms = [value.strip() for value in settings.oidc_algorithms.split(",") if value.strip()]
    if not algorithms:
        algorithms = ["RS256"]

    try:
        jwks_client = _get_jwks_client()
        signing_key = jwks_client.get_signing_key_from_jwt(token)
        verify_options = {
            "verify_aud": bool(settings.oidc_audience.strip()),
            "verify_iss": bool(settings.oidc_issuer.strip()),
        }
        claims = decode(
            token,
            signing_key.key,
            algorithms=algorithms,
            audience=settings.oidc_audience.strip() or None,
            issuer=settings.oidc_issuer.strip() or None,
            options=verify_options,
        )
    except (InvalidTokenError, PyJWKClientError, ValueError):
        return False

    principal = claims.get("sub") or claims.get("client_id") or claims.get("azp")
    if not principal:
        return False

    scopes = _extract_oidc_scopes(claims)
    if settings.oidc_scope_operator in scopes:
        resolved_scope = "operator"
    elif settings.oidc_scope_approver in scopes:
        resolved_scope = "approver"
    elif settings.oidc_scope_viewer in scopes:
        resolved_scope = "viewer"
    else:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="OIDC token does not include required CMDB scope",
        )

    request.state.service_principal = f"oidc:{principal}"
    request.state.service_scope = resolved_scope
    request.state.service_auth_source = "oidc"
    return True


def require_service_auth(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> str:
    settings = get_settings()
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

    mode = settings.service_auth_mode
    static_configured = bool(
        _split_tokens(settings.service_auth_tokens)
        or _split_tokens(settings.service_operator_tokens)
        or _split_tokens(settings.service_approver_tokens)
        or _split_tokens(settings.service_viewer_tokens)
    )
    oidc_configured = bool(settings.oidc_jwks_url.strip())

    if mode == "static":
        if not static_configured:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Static service authentication is not configured",
            )
        if _try_static_token_auth(request, token):
            return token
    elif mode == "hybrid":
        if _try_static_token_auth(request, token):
            return token
        if oidc_configured and _try_oidc_auth(request, token):
            return token
        if not static_configured and not oidc_configured:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Hybrid service authentication is not configured",
            )
    elif mode == "oidc":
        if not oidc_configured:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="OIDC service authentication is not configured",
            )
        if _try_oidc_auth(request, token):
            return token
    else:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Invalid authentication mode configuration",
        )

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


def require_approver_scope(request: Request) -> None:
    scope = getattr(request.state, "service_scope", None)
    if scope != "approver":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Approver scope required",
        )


async def _enforce_maker_checker(
    request: Request,
    db: Session,
) -> None:
    settings = get_settings()
    if not settings.maker_checker_enabled:
        return

    if request.url.path.startswith("/approvals"):
        return

    approval_id = request.headers.get("x-cmdb-approval-id", "").strip()
    if not approval_id:
        raise HTTPException(
            status_code=428,
            detail="x-cmdb-approval-id header is required for mutating requests",
        )

    approval = db.get(ChangeApproval, approval_id)
    if not approval:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Approval request not found")

    if approval.status != ApprovalStatus.APPROVED:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Approval is not in APPROVED state")

    now = utcnow()
    if approval.expires_at <= now:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Approval has expired")

    principal = getattr(request.state, "service_principal", "service:unknown")
    if settings.maker_checker_bind_requester and approval.requested_by != principal:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Approval is not bound to this requester",
        )

    if approval.method != request.method.upper():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Approval method mismatch")

    if approval.request_path != canonical_request_path(request):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Approval path mismatch")

    request_body = await request.body()
    payload_hash = canonical_payload_hash(request_body, request.headers.get("content-type"))
    if approval.payload_hash != payload_hash:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Approval payload hash mismatch")

    approval.status = ApprovalStatus.CONSUMED
    approval.consumed_at = now
    db.flush()


async def require_mutation_rate_limit(
    request: Request,
    db: Session = Depends(get_db),
) -> None:
    require_operator_scope(request)
    _apply_mutation_rate_limit(request)
    _enforce_mutation_payload_limit(request)
    await _enforce_maker_checker(request, db)


def require_approver_mutation_rate_limit(request: Request) -> None:
    require_approver_scope(request)
    _apply_mutation_rate_limit(request, approver=True)
    _enforce_mutation_payload_limit(request)
