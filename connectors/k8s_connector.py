from connectors.common import iso_now, post_ci_payload, pretty_print


def run() -> None:
    cis = [
        {
            "name": "payments-api",
            "ci_type": "k8s_workload",
            "owner": "payments",
            "attributes": {"namespace": "payments", "cluster": "prod-cluster"},
            "identities": [
                {"scheme": "k8s_uid", "value": "uid-12345"},
                {"scheme": "k8s_fqn", "value": "deployments/payments/payments-api"},
            ],
            "last_seen_at": iso_now(),
        }
    ]
    result = post_ci_payload("k8s", cis)
    pretty_print("Kubernetes ingest result:", result)


if __name__ == "__main__":
    run()
