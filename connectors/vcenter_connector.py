import httpx

from connectors.common import (
    env_bool,
    get_optional_env,
    get_required_env,
    http_get_json,
    iso_now,
    post_ci_payload,
    pretty_print,
)


def run() -> None:
    base_url = get_required_env("VSPHERE_URL").rstrip("/")
    username = get_required_env("VSPHERE_USERNAME")
    password = get_required_env("VSPHERE_PASSWORD")
    verify_ssl = env_bool("VSPHERE_VERIFY_SSL", default=True)
    default_owner = get_optional_env("VSPHERE_DEFAULT_OWNER", "infra-team")
    environment = get_optional_env("VSPHERE_ENVIRONMENT", "unknown")

    session_resp = httpx.post(
        f"{base_url}/rest/com/vmware/cis/session",
        auth=(username, password),
        timeout=30,
        verify=verify_ssl,
    )
    session_resp.raise_for_status()
    session_payload = session_resp.json()
    if not isinstance(session_payload, dict) or not isinstance(session_payload.get("value"), str):
        raise RuntimeError("Unable to get vCenter session token")
    token = session_payload["value"]
    headers = {"vmware-api-session-id": token}

    vm_response = http_get_json(
        f"{base_url}/rest/vcenter/vm",
        headers=headers,
        timeout=30,
        verify=verify_ssl,
    )
    vm_items = vm_response.get("value", [])
    if not isinstance(vm_items, list):
        vm_items = []

    cis: list[dict] = []
    for vm in vm_items:
        if not isinstance(vm, dict):
            continue
        vm_id = str(vm.get("vm", "")).strip()
        vm_name = str(vm.get("name") or f"vcenter-vm-{vm_id}").strip()
        if not vm_id or not vm_name:
            continue
        cis.append(
            {
                "name": vm_name,
                "ci_type": "vm",
                "owner": default_owner,
                "attributes": {
                    "environment": environment,
                    "power_state": vm.get("power_state"),
                    "cpu_count": vm.get("cpu_count"),
                    "memory_size_mib": vm.get("memory_size_MiB"),
                },
                "identities": [
                    {"scheme": "moid", "value": vm_id},
                    {"scheme": "hostname", "value": vm_name},
                ],
                "last_seen_at": iso_now(),
            }
        )

    if not cis:
        raise RuntimeError("No VM records collected from vCenter")

    result = post_ci_payload("vcenter", cis)
    pretty_print("vCenter ingest result:", result)


if __name__ == "__main__":
    run()
