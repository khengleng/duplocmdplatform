from pathlib import Path

from connectors.common import env_bool, get_optional_env, get_required_env, http_get_json, iso_now, post_ci_payload, pretty_print


def _k8s_auth_token() -> str:
    explicit = get_optional_env("K8S_BEARER_TOKEN")
    if explicit:
        return explicit
    token_path = Path("/var/run/secrets/kubernetes.io/serviceaccount/token")
    if token_path.exists():
        token = token_path.read_text(encoding="utf-8").strip()
        if token:
            return token
    raise RuntimeError("Missing Kubernetes bearer token (K8S_BEARER_TOKEN)")


def run() -> None:
    api_url = get_required_env("K8S_API_URL").rstrip("/")
    cluster_name = get_optional_env("K8S_CLUSTER_NAME", "k8s-cluster")
    environment = get_optional_env("K8S_ENVIRONMENT", "unknown")
    default_owner = get_optional_env("K8S_DEFAULT_OWNER", "platform-team")
    verify_ssl = env_bool("K8S_VERIFY_SSL", default=True)
    ca_cert = get_optional_env("K8S_CA_CERT_PATH", "/var/run/secrets/kubernetes.io/serviceaccount/ca.crt")

    verify: bool | str = verify_ssl
    if verify_ssl and ca_cert and Path(ca_cert).exists():
        verify = ca_cert

    headers = {"Authorization": f"Bearer {_k8s_auth_token()}"}

    url = f"{api_url}/apis/apps/v1/deployments"
    params: dict[str, str] = {"limit": "200"}
    deployments: list[dict] = []
    while True:
        payload = http_get_json(url, headers=headers, params=params, verify=verify, timeout=30)
        items = payload.get("items", [])
        if isinstance(items, list):
            for item in items:
                if isinstance(item, dict):
                    deployments.append(item)
        continue_token = (
            payload.get("metadata", {}).get("continue")
            if isinstance(payload.get("metadata"), dict)
            else None
        )
        if isinstance(continue_token, str) and continue_token:
            params["continue"] = continue_token
            continue
        break

    cis: list[dict] = []
    for deployment in deployments:
        metadata = deployment.get("metadata") if isinstance(deployment.get("metadata"), dict) else {}
        status = deployment.get("status") if isinstance(deployment.get("status"), dict) else {}
        spec = deployment.get("spec") if isinstance(deployment.get("spec"), dict) else {}
        labels = metadata.get("labels") if isinstance(metadata.get("labels"), dict) else {}

        name = str(metadata.get("name") or "").strip()
        namespace = str(metadata.get("namespace") or "default")
        uid = str(metadata.get("uid") or "").strip()
        if not name or not uid:
            continue
        owner = str(labels.get("owner") or labels.get("team") or default_owner)
        cis.append(
            {
                "name": name,
                "ci_type": "k8s_workload",
                "owner": owner,
                "attributes": {
                    "environment": environment,
                    "namespace": namespace,
                    "cluster": cluster_name,
                    "replicas": spec.get("replicas"),
                    "ready_replicas": status.get("readyReplicas"),
                    "available_replicas": status.get("availableReplicas"),
                    "labels": labels,
                },
                "identities": [
                    {"scheme": "k8s_uid", "value": uid},
                    {"scheme": "k8s_fqn", "value": f"deployments/{namespace}/{name}"},
                ],
                "last_seen_at": iso_now(),
            }
        )

    if not cis:
        raise RuntimeError("No deployment records collected from Kubernetes")

    result = post_ci_payload("k8s", cis)
    pretty_print("Kubernetes ingest result:", result)


if __name__ == "__main__":
    run()
