import json
import os
from datetime import datetime, timezone

import httpx


BASE_URL = "http://localhost:8000"


def post_ci_payload(source: str, cis: list[dict]) -> dict:
    payload = {"source": source, "cis": cis}
    headers: dict[str, str] = {}
    service_token = os.getenv("SERVICE_AUTH_TOKEN", "").strip()
    if service_token:
        headers["Authorization"] = f"Bearer {service_token}"
    response = httpx.post(f"{BASE_URL}/ingest/cis:bulk", json=payload, headers=headers, timeout=30)
    response.raise_for_status()
    return response.json()


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def pretty_print(title: str, data: dict) -> None:
    print(title)
    print(json.dumps(data, indent=2))
