import json
import os
from datetime import datetime, timezone

import httpx


BASE_URL = os.getenv("CMDB_BASE_URL", "http://localhost:8000").rstrip("/")


def _service_headers() -> dict[str, str]:
    headers: dict[str, str] = {}
    service_token = os.getenv("SERVICE_AUTH_TOKEN", "").strip()
    if service_token:
        headers["Authorization"] = f"Bearer {service_token}"
    return headers


def cmdb_ingest_url() -> str:
    return f"{BASE_URL}/ingest/cis:bulk"


def post_ci_payload(source: str, cis: list[dict], dry_run: bool = False) -> dict:
    payload = {"source": source, "cis": cis}
    url = cmdb_ingest_url()
    if dry_run:
        url = f"{url}?dryRun=true"
    response = httpx.post(url, json=payload, headers=_service_headers(), timeout=30)
    response.raise_for_status()
    return response.json()


def env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def get_required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def get_optional_env(name: str, default: str = "") -> str:
    value = os.getenv(name)
    return value.strip() if isinstance(value, str) else default


def http_get_json(
    url: str,
    headers: dict[str, str] | None = None,
    params: dict | None = None,
    timeout: int = 30,
    verify: bool | str = True,
) -> dict:
    response = httpx.get(url, headers=headers, params=params, timeout=timeout, verify=verify)
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict):
        raise RuntimeError("Expected JSON object response")
    return data


def http_post_json(
    url: str,
    body: dict,
    headers: dict[str, str] | None = None,
    timeout: int = 30,
    verify: bool | str = True,
    auth: tuple[str, str] | None = None,
) -> dict:
    response = httpx.post(url, json=body, headers=headers, timeout=timeout, verify=verify, auth=auth)
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict):
        raise RuntimeError("Expected JSON object response")
    return data


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def pretty_print(title: str, data: dict) -> None:
    print(title)
    print(json.dumps(data, indent=2))
