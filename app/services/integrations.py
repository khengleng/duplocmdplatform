import base64
import hashlib
import hmac
import json
import logging
import time
from typing import Any

import httpx

from app.core.config import get_settings
from app.core.logging import correlation_id_ctx
from app.schemas import CIPayload

logger = logging.getLogger(__name__)
settings = get_settings()


def _authorization_value(token: str) -> str:
    value = token.strip()
    lower = value.lower()
    if lower.startswith("bearer ") or lower.startswith("token "):
        return value
    return f"Bearer {value}"


def _request_headers(token: str) -> dict[str, str]:
    headers = {
        "Content-Type": "application/json",
        "X-Source-System": settings.unified_cmdb_name,
    }
    correlation_id = correlation_id_ctx.get()
    if correlation_id:
        headers["x-correlation-id"] = correlation_id
    if token:
        headers["Authorization"] = _authorization_value(token)
    return headers


def _post_json(url: str, token: str, body: dict[str, Any], target: str) -> dict[str, Any]:
    if not url:
        return {"status": "skipped", "reason": f"{target}_url_missing"}
    try:
        response = httpx.post(url, json=body, headers=_request_headers(token), timeout=20)
        response.raise_for_status()
        return {"status": "sent", "status_code": response.status_code}
    except httpx.HTTPStatusError as exc:
        logger.warning(
            "Integration delivery rejected by upstream",
            extra={
                "target": target,
                "status_code": exc.response.status_code,
            },
        )
        return {
            "status": "failed",
            "error": "upstream_rejected",
            "status_code": exc.response.status_code,
        }
    except Exception:
        logger.exception("Integration delivery failed", extra={"target": target})
        return {"status": "failed", "error": "delivery_failed"}


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("utf-8").rstrip("=")


def _b64url_decode(data: str) -> bytes:
    normalized = data.strip().replace("-", "+").replace("_", "/")
    padded = normalized + ("=" * ((4 - len(normalized) % 4) % 4))
    return base64.b64decode(padded)


def _legacy_backstage_token(secret: str) -> str:
    key = _b64url_decode(secret)
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {"sub": "backstage-server", "exp": int(time.time()) + 3600}
    encoded_header = _b64url_encode(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    encoded_payload = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signing_input = f"{encoded_header}.{encoded_payload}".encode("utf-8")
    signature = hmac.new(key, signing_input, hashlib.sha256).digest()
    return f"{encoded_header}.{encoded_payload}.{_b64url_encode(signature)}"


def _backstage_token() -> str:
    if settings.backstage_sync_token:
        return settings.backstage_sync_token
    if settings.backstage_sync_secret:
        try:
            return _legacy_backstage_token(settings.backstage_sync_secret)
        except Exception:
            logger.exception("Unable to generate Backstage legacy token")
    return ""


def _backstage_ingest_url(kind: str) -> str:
    base = settings.backstage_sync_url.strip().rstrip("/")
    if not base:
        return ""
    if base.endswith("/ingest/cis:bulk") or base.endswith("/ingest/relationships:bulk"):
        prefix = base.rsplit("/ingest/", 1)[0]
        return f"{prefix}/ingest/{kind}"
    return f"{base}/ingest/{kind}"


def _ci_to_backstage_item(ci_payload: dict[str, Any]) -> dict[str, Any]:
    attributes = ci_payload.get("attributes")
    if not isinstance(attributes, dict):
        attributes = {}
    environment = ci_payload.get("environment") or attributes.get("environment") or "unknown"
    ci_class = ci_payload.get("ciClass") or ci_payload.get("ci_type") or "unknown"
    canonical_name = ci_payload.get("canonicalName") or ci_payload.get("name") or ci_payload.get("id") or "unknown"
    lifecycle_state = ci_payload.get("lifecycleState") or ci_payload.get("status") or "ACTIVE"
    status = ci_payload.get("status") or lifecycle_state

    identities = ci_payload.get("identities")
    if not isinstance(identities, list):
        identities = []
    ci_id = ci_payload.get("id")
    if ci_id and not any(isinstance(entry, dict) and entry.get("scheme") == "cmdb_ci_id" for entry in identities):
        identities.append({"scheme": "cmdb_ci_id", "value": str(ci_id)})

    item: dict[str, Any] = {
        "ciClass": str(ci_class),
        "canonicalName": str(canonical_name),
        "environment": str(environment),
        "lifecycleState": str(lifecycle_state),
        "status": str(status),
        "sourceSystem": ci_payload.get("sourceSystem") or settings.unified_cmdb_name,
    }
    technical_owner = ci_payload.get("technicalOwner") or ci_payload.get("owner")
    if technical_owner:
        item["technicalOwner"] = str(technical_owner)

    support_group = ci_payload.get("supportGroup") or attributes.get("support_group")
    if support_group:
        item["supportGroup"] = str(support_group)

    if identities:
        item["identities"] = identities
    if attributes:
        item["attributes"] = attributes

    return item


def _relationship_to_backstage_item(payload: dict[str, Any]) -> dict[str, Any] | None:
    source_ci_id = payload.get("fromCiId") or payload.get("source_ci_id")
    target_ci_id = payload.get("toCiId") or payload.get("target_ci_id")
    if not source_ci_id or not target_ci_id:
        return None
    return {
        "fromCiId": source_ci_id,
        "toCiId": target_ci_id,
        "type": payload.get("type") or payload.get("relation_type") or "depends_on",
        "sourceSystem": payload.get("sourceSystem") or settings.unified_cmdb_name,
    }


def _publish_backstage_event(event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    token = _backstage_token()
    if not token:
        return {"status": "skipped", "reason": "backstage_auth_missing"}

    if event_type in {"ci.created", "ci.updated"}:
        message = {
            "sourceSystem": settings.unified_cmdb_name,
            "items": [_ci_to_backstage_item(payload)],
        }
        return _post_json(
            _backstage_ingest_url("cis:bulk"),
            token,
            message,
            target="backstage",
        )

    if event_type == "relationship.created":
        relationship_item = _relationship_to_backstage_item(payload)
        if not relationship_item:
            return {"status": "skipped", "reason": "invalid_relationship_payload"}
        message = {
            "sourceSystem": settings.unified_cmdb_name,
            "items": [relationship_item],
        }
        return _post_json(
            _backstage_ingest_url("relationships:bulk"),
            token,
            message,
            target="backstage",
        )

    return {"status": "skipped", "reason": "event_not_supported"}


def publish_backstage_bulk_cis(items: list[dict[str, Any]], dry_run: bool = False) -> dict[str, Any]:
    if not settings.backstage_sync_enabled:
        return {"status": "skipped", "reason": "backstage_sync_disabled"}
    if dry_run:
        return {"status": "staged", "staged": len(items)}

    token = _backstage_token()
    if not token:
        return {"status": "skipped", "reason": "backstage_auth_missing"}

    message = {
        "sourceSystem": settings.unified_cmdb_name,
        "items": [_ci_to_backstage_item(item) for item in items],
    }
    result = _post_json(_backstage_ingest_url("cis:bulk"), token, message, target="backstage")
    result["attempted"] = len(items)
    return result


def _publish_event(url: str, token: str, event_type: str, payload: dict[str, Any], target: str) -> dict[str, Any]:
    body = {
        "eventType": event_type,
        "sourceSystem": settings.unified_cmdb_name,
        "payload": payload,
    }
    return _post_json(url, token, body, target)


def _netbox_api_base_url() -> str:
    base = settings.netbox_api_url.strip().rstrip("/")
    if not base:
        return ""
    if base.endswith("/api"):
        return base
    return f"{base}/api"


def _netbox_auth_header_value() -> str:
    if not settings.netbox_api_token:
        return ""
    token = settings.netbox_api_token.strip()
    lower = token.lower()
    if lower.startswith("bearer ") or lower.startswith("token "):
        return token
    return f"Bearer {token}"


def _netbox_extract_name(value: Any) -> str | None:
    if isinstance(value, dict):
        name = value.get("name")
        if isinstance(name, str) and name:
            return name
    return None


def _netbox_collect(endpoint: str, max_items: int) -> list[dict[str, Any]]:
    base_url = _netbox_api_base_url()
    auth_header = _netbox_auth_header_value()
    if not base_url:
        raise ValueError("netbox_api_url_missing")
    if not auth_header:
        raise ValueError("netbox_api_token_missing")

    url = f"{base_url}{endpoint}" if endpoint.startswith("/") else f"{base_url}/{endpoint}"
    headers = {
        "Accept": "application/json",
        "Authorization": auth_header,
    }

    items: list[dict[str, Any]] = []
    while url and len(items) < max_items:
        response = httpx.get(url, headers=headers, timeout=20)
        response.raise_for_status()
        payload = response.json()
        results = payload.get("results")
        if not isinstance(results, list):
            break
        for result in results:
            if isinstance(result, dict):
                items.append(result)
            if len(items) >= max_items:
                break
        next_url = payload.get("next")
        url = next_url if isinstance(next_url, str) and next_url else ""
    return items


def fetch_netbox_cis(limit: int = 500) -> list[CIPayload]:
    if limit < 1:
        return []

    half = max(1, limit // 2)
    device_records = _netbox_collect("/dcim/devices/?limit=100", max_items=half)
    vm_records = _netbox_collect("/virtualization/virtual-machines/?limit=100", max_items=max(1, limit - half))

    payloads: list[CIPayload] = []
    for record in device_records:
        device_id = record.get("id")
        name = record.get("name") or f"netbox-device-{device_id}"
        status_name = _netbox_extract_name(record.get("status")) or "unknown"
        tenant_name = _netbox_extract_name(record.get("tenant"))
        attributes = {
            "environment": "unknown",
            "netbox_object": "device",
            "netbox_status": status_name,
            "site": _netbox_extract_name(record.get("site")),
            "role": _netbox_extract_name(record.get("role")),
            "tenant": tenant_name,
            "primary_ip4": _netbox_extract_name(record.get("primary_ip4")),
            "primary_ip6": _netbox_extract_name(record.get("primary_ip6")),
            "url": record.get("url"),
        }
        attributes = {k: v for k, v in attributes.items() if v is not None}

        identities = [{"scheme": "netbox_device_id", "value": str(device_id)}]
        if name:
            identities.append({"scheme": "hostname", "value": str(name)})

        payloads.append(
            CIPayload(
                name=str(name),
                ci_type="netbox_device",
                owner=tenant_name,
                attributes=attributes,
                identities=identities,
                last_seen_at=None,
            )
        )

    for record in vm_records:
        vm_id = record.get("id")
        name = record.get("name") or f"netbox-vm-{vm_id}"
        status_name = _netbox_extract_name(record.get("status")) or "unknown"
        tenant_name = _netbox_extract_name(record.get("tenant"))
        attributes = {
            "environment": "unknown",
            "netbox_object": "virtual_machine",
            "netbox_status": status_name,
            "cluster": _netbox_extract_name(record.get("cluster")),
            "role": _netbox_extract_name(record.get("role")),
            "tenant": tenant_name,
            "primary_ip4": _netbox_extract_name(record.get("primary_ip4")),
            "primary_ip6": _netbox_extract_name(record.get("primary_ip6")),
            "vcpus": record.get("vcpus"),
            "memory": record.get("memory"),
            "disk": record.get("disk"),
            "url": record.get("url"),
        }
        attributes = {k: v for k, v in attributes.items() if v is not None}

        identities = [{"scheme": "netbox_vm_id", "value": str(vm_id)}]
        if name:
            identities.append({"scheme": "hostname", "value": str(name)})

        payloads.append(
            CIPayload(
                name=str(name),
                ci_type="netbox_vm",
                owner=tenant_name,
                attributes=attributes,
                identities=identities,
                last_seen_at=None,
            )
        )

    return payloads[:limit]


def publish_ci_event(event_type: str, payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}

    if settings.netbox_sync_enabled:
        result["netbox"] = _publish_event(
            settings.netbox_sync_url,
            settings.netbox_sync_token,
            event_type,
            payload,
            target="netbox",
        )
    else:
        result["netbox"] = {"status": "skipped", "reason": "netbox_sync_disabled"}

    if settings.backstage_sync_enabled:
        result["backstage"] = _publish_backstage_event(event_type, payload)
    else:
        result["backstage"] = {"status": "skipped", "reason": "backstage_sync_disabled"}

    return result
