from connectors.common import iso_now, post_ci_payload, pretty_print


def run() -> None:
    cis = [
        {
            "name": "zbx-db-01",
            "ci_type": "vm",
            "owner": "platform-team",
            "attributes": {"ip": "10.1.1.10", "environment": "prod"},
            "identities": [
                {"scheme": "hostname", "value": "zbx-db-01"},
                {"scheme": "zabbix_id", "value": "10001"},
            ],
            "last_seen_at": iso_now(),
        }
    ]
    result = post_ci_payload("zabbix", cis)
    pretty_print("Zabbix ingest result:", result)


if __name__ == "__main__":
    run()
