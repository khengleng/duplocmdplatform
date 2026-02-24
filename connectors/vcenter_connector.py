from connectors.common import iso_now, post_ci_payload, pretty_print


def run() -> None:
    cis = [
        {
            "name": "vc-app-01",
            "ci_type": "vm",
            "owner": "infra-team",
            "attributes": {"cluster": "cluster-a", "datacenter": "dc1"},
            "identities": [
                {"scheme": "hostname", "value": "vc-app-01"},
                {"scheme": "moid", "value": "vm-550"},
            ],
            "last_seen_at": iso_now(),
        }
    ]
    result = post_ci_payload("vcenter", cis)
    pretty_print("vCenter ingest result:", result)


if __name__ == "__main__":
    run()
