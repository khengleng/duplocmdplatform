from connectors.common import (
    get_optional_env,
    get_required_env,
    http_post_json,
    iso_now,
    post_ci_payload,
    pretty_print,
)


def _zabbix_rpc(url: str, method: str, params: dict, token: str | None, request_id: int = 1) -> dict:
    body = {"jsonrpc": "2.0", "method": method, "params": params, "id": request_id}
    if token:
        body["auth"] = token
    result = http_post_json(url, body=body, headers={"Content-Type": "application/json-rpc"})
    if "error" in result:
        raise RuntimeError(f"Zabbix API error: {result['error']}")
    return result


def _get_zabbix_auth_token(url: str) -> str:
    api_token = get_optional_env("ZABBIX_API_TOKEN")
    if api_token:
        return api_token

    username = get_required_env("ZABBIX_USERNAME")
    password = get_required_env("ZABBIX_PASSWORD")
    login = _zabbix_rpc(
        url,
        method="user.login",
        params={"username": username, "password": password},
        token=None,
    )
    token = login.get("result")
    if not isinstance(token, str) or not token:
        raise RuntimeError("Unable to authenticate to Zabbix")
    return token


def _collect_hosts(url: str, token: str) -> list[dict]:
    result = _zabbix_rpc(
        url,
        method="host.get",
        params={
            "output": ["hostid", "host", "name", "status"],
            "selectGroups": ["name"],
            "selectInterfaces": ["ip", "dns"],
        },
        token=token,
    )
    hosts = result.get("result", [])
    if not isinstance(hosts, list):
        return []
    return [entry for entry in hosts if isinstance(entry, dict)]


def run() -> None:
    zabbix_base = get_required_env("ZABBIX_URL").rstrip("/")
    zabbix_rpc_url = f"{zabbix_base}/api_jsonrpc.php"
    default_owner = get_optional_env("ZABBIX_DEFAULT_OWNER", "platform-team")
    environment = get_optional_env("ZABBIX_ENVIRONMENT", "unknown")

    token = _get_zabbix_auth_token(zabbix_rpc_url)
    hosts = _collect_hosts(zabbix_rpc_url, token)

    cis: list[dict] = []
    for host in hosts:
        host_id = str(host.get("hostid", "")).strip()
        host_name = str(host.get("name") or host.get("host") or f"zabbix-host-{host_id}").strip()
        if not host_id or not host_name:
            continue
        groups = [g.get("name") for g in host.get("groups", []) if isinstance(g, dict) and g.get("name")]
        interfaces = [i for i in host.get("interfaces", []) if isinstance(i, dict)]
        primary_ip = next((iface.get("ip") for iface in interfaces if iface.get("ip")), None)
        primary_dns = next((iface.get("dns") for iface in interfaces if iface.get("dns")), None)

        cis.append(
            {
                "name": host_name,
                "ci_type": "host",
                "owner": default_owner,
                "attributes": {
                    "environment": environment,
                    "zabbix_status": host.get("status"),
                    "groups": groups,
                    "primary_ip": primary_ip,
                    "primary_dns": primary_dns,
                },
                "identities": [
                    {"scheme": "zabbix_host_id", "value": host_id},
                    {"scheme": "hostname", "value": host_name},
                ],
                "last_seen_at": iso_now(),
            }
        )

    if not cis:
        raise RuntimeError("No host records collected from Zabbix")

    result = post_ci_payload("zabbix", cis)
    pretty_print("Zabbix ingest result:", result)


if __name__ == "__main__":
    run()
