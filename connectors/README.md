# Source Connectors

These connectors pull live inventory from source systems and publish normalized
CI payloads to `POST /ingest/cis:bulk` in unifiedCMDB.

## Usage

1. Start the CMDB Core service.
2. Set connector environment variables.
3. Run a connector script:

```bash
export CMDB_BASE_URL=http://localhost:8000
export SERVICE_AUTH_TOKEN=<cmdb-service-token>

python -m connectors.zabbix_connector
python -m connectors.vcenter_connector
python -m connectors.azure_connector
python -m connectors.k8s_connector
```

## Required Variables By Connector

`zabbix_connector.py`
- `ZABBIX_URL`
- one of:
  - `ZABBIX_API_TOKEN`
  - `ZABBIX_USERNAME` + `ZABBIX_PASSWORD`

Optional:
- `ZABBIX_DEFAULT_OWNER`
- `ZABBIX_ENVIRONMENT`

`vcenter_connector.py`
- `VSPHERE_URL`
- `VSPHERE_USERNAME`
- `VSPHERE_PASSWORD`

Optional:
- `VSPHERE_VERIFY_SSL` (default `true`)
- `VSPHERE_DEFAULT_OWNER`
- `VSPHERE_ENVIRONMENT`

`azure_connector.py`
- `AZURE_SUBSCRIPTION_ID`
- one of:
  - `AZURE_ACCESS_TOKEN`
  - `AZURE_TENANT_ID` + `AZURE_CLIENT_ID` + `AZURE_CLIENT_SECRET`

Optional:
- `AZURE_DEFAULT_OWNER`
- `AZURE_ENVIRONMENT`

`k8s_connector.py`
- `K8S_API_URL`
- one of:
  - `K8S_BEARER_TOKEN`
  - in-cluster service account token file

Optional:
- `K8S_CLUSTER_NAME`
- `K8S_ENVIRONMENT`
- `K8S_DEFAULT_OWNER`
- `K8S_VERIFY_SSL` (default `true`)
- `K8S_CA_CERT_PATH`
