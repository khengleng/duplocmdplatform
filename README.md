# Thin CMDB Core + Connectors

This repository provides a thin CMDB Core service and stub connectors for:

- Zabbix
- vCenter
- Azure
- Kubernetes

`unifiedCMDB` acts as the integration hub between:

- CMDB Core (single write authority)
- NetBox project (downstream consumer/sync target)
- Backstage project (catalog/read + connector ingest)

## Implemented Modules

1. Identity Registry
- Unique identity constraint on `(scheme, value)`
- Collision detection with governance records

2. Reconciliation Engine
- Source-based attribute precedence (`SOURCE_PRECEDENCE`)
- Collision workflow creates governance events and Jira issue stubs

3. Lifecycle Engine
- `30` days inactive -> `STAGING`
- `90` days inactive -> `RETIREMENT_REVIEW`
- `120` days inactive -> `RETIRED`

4. Audit Ledger
- Immutable append-only audit event table
- ELK-friendly export endpoint: `GET /audit/export`

5. REST API
- `POST /ingest/cis:bulk`
- `POST /ingest/relationships:bulk`
- `GET /cis`
- `GET /cis/{id}`
- `GET /cis/{id}/graph`
- `GET /cis/{id}/audit`
- `GET /pickers/cis`
- `POST /governance/collisions/{id}/resolve`

Backstage compatibility (verified against local Backstage source):
- `POST /ingest/cis:bulk` accepts `{ sourceSystem, items }` and `{ source, cis }`
- `POST /ingest/relationships:bulk` accepts `{ items }` and `{ source, relationships }`
- `GET /cis` includes compatibility fields: `ciClass`, `canonicalName`, `environment`, `lifecycleState`, `technicalOwner`

Additional utility endpoints:
- `GET /health`
- `POST /lifecycle/run`
- `GET /governance/collisions`
- `GET /integrations/status`
- `GET /integrations/backstage/entities`
- `GET /integrations/netbox/export`
- `POST /integrations/netbox/import`
- `POST /integrations/backstage/sync`

## Local Development

### Option 1: Docker Compose

```bash
docker compose up --build
```

Service will be available at `http://localhost:8000`.

### Option 2: Local Python

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload
```

## OpenAPI

- Swagger UI: `http://localhost:8000/docs`
- OpenAPI JSON: `http://localhost:8000/openapi.json`

## Jira Integration

Jira integration is enabled with environment variables:

- `JIRA_ENABLED=true`
- `JIRA_BASE_URL=https://your-jira.example.com`
- `JIRA_PROJECT_KEY=CMDB`
- `JIRA_TOKEN=<token>`

If disabled, issue creation is logged and skipped.

## NetBox And Backstage Glue

Use these environment variables to activate outbound sync webhooks:

- `UNIFIED_CMDB_NAME=unifiedCMDB`
- `NETBOX_SYNC_ENABLED=true`
- `NETBOX_SYNC_URL=https://<netbox-adapter-endpoint>`
- `NETBOX_SYNC_TOKEN=<token>`
- `BACKSTAGE_SYNC_ENABLED=true`
- `BACKSTAGE_SYNC_URL=https://<backstage-base>/api/cmdb`
- `BACKSTAGE_SYNC_TOKEN=<token>`
- `BACKSTAGE_SYNC_SECRET=<legacy-externalAccess secret (base64/base64url)>` (optional alternative to token)

NetBox pull import configuration:

- `NETBOX_API_URL=https://<netbox-host>` (or `.../api`)
- `NETBOX_API_TOKEN=<Bearer nbt_<key>.<secret> token or raw token>`

If disabled, unifiedCMDB still provides pull-based integration endpoints for both projects.

Backstage source note:

- Backstage CMDB backend write access must allow unifiedCMDB's service subject.
- Add `external:backstage-plugin` under `cmdb.auth.allowedServiceSubjects` in Backstage config.

## Logging

Structured JSON logs are emitted with `correlationId`.
Incoming `x-correlation-id` header is preserved; otherwise one is generated per request.
