# Connector Stubs

These are stub connectors for Zabbix, vCenter, Azure, and Kubernetes.

## Usage

1. Start the CMDB Core service on `http://localhost:8000`.
2. Run a connector script:

```bash
python -m connectors.zabbix_connector
python -m connectors.vcenter_connector
python -m connectors.azure_connector
python -m connectors.k8s_connector
```

Each script normalizes a sample payload and posts it to `POST /ingest/cis:bulk`.
