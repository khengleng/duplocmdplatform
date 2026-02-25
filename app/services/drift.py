from typing import Any
from urllib.parse import quote, urlparse

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import CI, Identity

settings = get_settings()


def _is_non_dev_environment() -> bool:
    return settings.app_env.strip().lower() not in {"dev", "development", "local", "test"}


def _valid_base_url(value: str) -> str:
    base = value.strip().rstrip("/")
    if not base:
        return ""
    parsed = urlparse(base)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    if _is_non_dev_environment() and parsed.scheme != "https":
        return ""
    return base


def _netbox_api_base_url() -> str:
    base = _valid_base_url(settings.netbox_api_url)
    if not base:
        return ""
    if base.endswith("/api"):
        return base
    return f"{base}/api"


def _netbox_auth_header_value() -> str:
    token = settings.netbox_api_token.strip()
    if not token:
        return ""
    lower = token.lower()
    if lower.startswith("bearer ") or lower.startswith("token "):
        return token
    return f"Bearer {token}"


def _ci_projection(ci: CI) -> dict[str, Any]:
    attributes = ci.attributes if isinstance(ci.attributes, dict) else {}
    return {
        "id": ci.id,
        "name": ci.name,
        "ci_type": ci.ci_type,
        "owner": ci.owner,
        "status": ci.status.value,
        "environment": attributes.get("environment", "unknown"),
        "source": ci.source,
    }


def _compare_fields(reference: dict[str, Any], target: dict[str, Any], fields: list[str]) -> list[dict[str, Any]]:
    mismatches: list[dict[str, Any]] = []
    for field in fields:
        if reference.get(field) != target.get(field):
            mismatches.append(
                {
                    "field": field,
                    "cmdb": reference.get(field),
                    "target": target.get(field),
                }
            )
    return mismatches


def _netbox_state_for_ci(db: Session, ci: CI) -> dict[str, Any]:
    base_url = _netbox_api_base_url()
    auth = _netbox_auth_header_value()
    if not base_url:
        return {"status": "unavailable", "reason": "netbox_api_url_missing"}
    if not auth:
        return {"status": "unavailable", "reason": "netbox_api_token_missing"}

    identities = list(db.scalars(select(Identity).where(Identity.ci_id == ci.id)))
    device_id = next((identity.value for identity in identities if identity.scheme == "netbox_device_id"), None)
    vm_id = next((identity.value for identity in identities if identity.scheme == "netbox_vm_id"), None)

    target_url = ""
    netbox_kind = ""
    if device_id:
        target_url = f"{base_url}/dcim/devices/{device_id}/"
        netbox_kind = "device"
    elif vm_id:
        target_url = f"{base_url}/virtualization/virtual-machines/{vm_id}/"
        netbox_kind = "virtual_machine"
    else:
        return {"status": "not_applicable", "reason": "no_netbox_identity"}

    headers = {"Accept": "application/json", "Authorization": auth}
    try:
        response = httpx.get(target_url, headers=headers, timeout=20)
        if response.status_code == 404:
            return {"status": "missing", "reason": "not_found", "kind": netbox_kind}
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            return {"status": "error", "reason": "invalid_response", "kind": netbox_kind}
    except Exception:
        return {"status": "error", "reason": "request_failed", "kind": netbox_kind}

    target_projection = {
        "name": payload.get("name"),
        "status": (payload.get("status") or {}).get("value") if isinstance(payload.get("status"), dict) else payload.get("status"),
        "owner": (payload.get("tenant") or {}).get("name") if isinstance(payload.get("tenant"), dict) else None,
    }
    cmdb_projection = _ci_projection(ci)
    mismatches = _compare_fields(cmdb_projection, target_projection, ["name"])
    return {
        "status": "matched" if not mismatches else "drift",
        "kind": netbox_kind,
        "target": target_projection,
        "mismatches": mismatches,
    }


def _backstage_state_for_ci(ci: CI) -> dict[str, Any]:
    catalog_base = _valid_base_url(settings.backstage_catalog_url)
    if not catalog_base:
        return {"status": "unavailable", "reason": "backstage_catalog_url_missing"}

    headers = {"Accept": "application/json"}
    token = settings.backstage_catalog_token.strip()
    if token:
        headers["Authorization"] = f"Bearer {token}" if not token.lower().startswith("bearer ") else token

    filter_value = quote(f"metadata.annotations.unifiedcmdb.io/ci-id={ci.id}", safe=":=.")
    url = f"{catalog_base}/entities/by-query?filter={filter_value}&limit=1"

    try:
        response = httpx.get(url, headers=headers, timeout=20)
        if response.status_code == 404:
            return {"status": "missing", "reason": "not_found"}
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            return {"status": "error", "reason": "invalid_response"}
    except Exception:
        return {"status": "error", "reason": "request_failed"}

    items = payload.get("items")
    if not isinstance(items, list) or not items:
        return {"status": "missing", "reason": "not_found"}
    entity = items[0] if isinstance(items[0], dict) else {}
    metadata = entity.get("metadata") if isinstance(entity.get("metadata"), dict) else {}
    spec = entity.get("spec") if isinstance(entity.get("spec"), dict) else {}
    target_projection = {
        "name": metadata.get("title") or metadata.get("name"),
        "ci_type": spec.get("type"),
        "owner": spec.get("owner"),
    }
    cmdb_projection = _ci_projection(ci)
    mismatches = _compare_fields(cmdb_projection, target_projection, ["name", "ci_type", "owner"])
    return {
        "status": "matched" if not mismatches else "drift",
        "target": target_projection,
        "mismatches": mismatches,
    }


def compute_ci_drift(db: Session, ci: CI) -> dict[str, Any]:
    cmdb = _ci_projection(ci)
    netbox = _netbox_state_for_ci(db, ci)
    backstage = _backstage_state_for_ci(ci)
    overall_status = "clean"
    if netbox.get("status") in {"drift", "missing", "error"} or backstage.get("status") in {"drift", "missing", "error"}:
        overall_status = "drift_detected"
    return {
        "ci_id": ci.id,
        "overall_status": overall_status,
        "cmdb": cmdb,
        "netbox": netbox,
        "backstage": backstage,
    }
