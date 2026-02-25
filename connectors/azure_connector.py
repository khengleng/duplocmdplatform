import httpx

from connectors.common import get_optional_env, get_required_env, http_get_json, iso_now, post_ci_payload, pretty_print


def run() -> None:
    subscription_id = get_required_env("AZURE_SUBSCRIPTION_ID")
    environment = get_optional_env("AZURE_ENVIRONMENT", "unknown")
    default_owner = get_optional_env("AZURE_DEFAULT_OWNER", "cloud-platform")

    access_token = get_optional_env("AZURE_ACCESS_TOKEN")
    if not access_token:
        tenant_id = get_required_env("AZURE_TENANT_ID")
        client_id = get_required_env("AZURE_CLIENT_ID")
        client_secret = get_required_env("AZURE_CLIENT_SECRET")
        token_body = {
            "client_id": client_id,
            "client_secret": client_secret,
            "grant_type": "client_credentials",
            "scope": "https://management.azure.com/.default",
        }
        token_http = httpx.post(
            f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token",
            data=token_body,
            timeout=30,
        )
        token_http.raise_for_status()
        token_resp = token_http.json()
        if not isinstance(token_resp, dict):
            raise RuntimeError("Invalid Azure token response")
        access_token = str(token_resp.get("access_token", "")).strip()
        if not access_token:
            raise RuntimeError("Unable to acquire Azure access token")

    headers = {"Authorization": f"Bearer {access_token}"}
    api_version = "2024-03-01"
    url = (
        f"https://management.azure.com/subscriptions/{subscription_id}"
        f"/providers/Microsoft.Compute/virtualMachines?api-version={api_version}"
    )

    vm_items: list[dict] = []
    while url:
        payload = http_get_json(url, headers=headers, timeout=30)
        values = payload.get("value", [])
        if isinstance(values, list):
            for entry in values:
                if isinstance(entry, dict):
                    vm_items.append(entry)
        next_link = payload.get("nextLink")
        url = str(next_link) if isinstance(next_link, str) and next_link else ""

    cis: list[dict] = []
    for vm in vm_items:
        vm_name = str(vm.get("name") or "").strip()
        vm_id = str(vm.get("id") or "").strip()
        if not vm_name or not vm_id:
            continue
        tags = vm.get("tags") if isinstance(vm.get("tags"), dict) else {}
        owner = str(tags.get("owner") or default_owner)
        resource_group = "unknown"
        parts = vm_id.split("/")
        if "resourceGroups" in parts:
            idx = parts.index("resourceGroups")
            if idx + 1 < len(parts):
                resource_group = parts[idx + 1]

        properties = vm.get("properties") if isinstance(vm.get("properties"), dict) else {}
        hardware = properties.get("hardwareProfile") if isinstance(properties.get("hardwareProfile"), dict) else {}
        storage = properties.get("storageProfile") if isinstance(properties.get("storageProfile"), dict) else {}
        os_disk = storage.get("osDisk") if isinstance(storage.get("osDisk"), dict) else {}

        cis.append(
            {
                "name": vm_name,
                "ci_type": "vm",
                "owner": owner,
                "attributes": {
                    "environment": environment,
                    "subscription": subscription_id,
                    "resource_group": resource_group,
                    "location": vm.get("location"),
                    "vm_size": hardware.get("vmSize"),
                    "provisioning_state": properties.get("provisioningState"),
                    "os_type": os_disk.get("osType"),
                },
                "identities": [
                    {"scheme": "azure_resource_id", "value": vm_id},
                    {"scheme": "hostname", "value": vm_name},
                ],
                "last_seen_at": iso_now(),
            }
        )

    if not cis:
        raise RuntimeError("No VM records collected from Azure")

    result = post_ci_payload("azure", cis)
    pretty_print("Azure ingest result:", result)


if __name__ == "__main__":
    run()
