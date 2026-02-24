from connectors.common import iso_now, post_ci_payload, pretty_print


def run() -> None:
    cis = [
        {
            "name": "az-node-01",
            "ci_type": "vm",
            "owner": "cloud-platform",
            "attributes": {"subscription": "sub-a", "resource_group": "rg-core"},
            "identities": [
                {"scheme": "azure_resource_id", "value": "/subscriptions/sub-a/resourceGroups/rg-core/providers/Microsoft.Compute/virtualMachines/az-node-01"},
                {"scheme": "hostname", "value": "az-node-01"},
            ],
            "last_seen_at": iso_now(),
        }
    ]
    result = post_ci_payload("azure", cis)
    pretty_print("Azure ingest result:", result)


if __name__ == "__main__":
    run()
