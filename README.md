# Thin CMDB Core + Connectors

This repository provides a thin CMDB Core service and source connectors for:

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
- Deterministic identity linking rules:
  - `netbox_device_id` / `netbox_vm_id` enrichment from payload attributes
  - Backstage annotation mapping (`unifiedcmdb.io/ci-id` -> `cmdb_ci_id`)
  - Backstage entity reference mapping (`kind:namespace/name` -> `backstage_entity_ref`)

3. Lifecycle Engine
- `30` days inactive -> `STAGING`
- `90` days inactive -> `RETIREMENT_REVIEW`
- `120` days inactive -> `RETIRED`

4. Audit Ledger
- Immutable append-only audit event table
- ELK-friendly export endpoint: `GET /audit/export`

5. Sync Job Orchestration
- Persistent queued/running/succeeded/failed sync jobs
- Automatic retry with exponential backoff
- Job status tracking endpoints and audit events
- Optional periodic scheduler for NetBox import and Backstage sync

6. REST API
- `POST /ingest/cis:bulk`
- `POST /ingest/relationships:bulk`
- `GET /cis`
- `GET /cis/{id}`
- `GET /cis/{id}/detail`
- `GET /cis/{id}/identities`
- `GET /cis/{id}/drift`
- `POST /cis/{id}/drift/resolve`
- `GET /cis/{id}/graph`
- `GET /cis/{id}/audit`
- `GET /pickers/cis`
- `POST /governance/collisions/{id}/resolve`
- `POST /governance/collisions/{id}/reopen`
- `GET /approvals`
- `POST /approvals`
- `POST /approvals/{id}/approve`
- `POST /approvals/{id}/reject`
- `GET /relationships`
- `POST /relationships`
- `PATCH /relationships/{id}`
- `DELETE /relationships/{id}`

Backstage compatibility (verified against local Backstage source):
- `POST /ingest/cis:bulk` accepts `{ sourceSystem, items }` and `{ source, cis }`
- `POST /ingest/relationships:bulk` accepts `{ items }` and `{ source, relationships }`
- `GET /cis` includes compatibility fields: `ciClass`, `canonicalName`, `environment`, `lifecycleState`, `technicalOwner`

Additional utility endpoints:
- `GET /health`
- `GET /portal` (web UI shell)
- `GET /dashboard/summary` (secured aggregate dashboard API)
- `GET /dashboard/activity` (secured recent activity API)
- `GET /dashboard/alerts` (secured 5-minute security alert snapshot API)
- `POST /lifecycle/run`
- `GET /governance/collisions`
- `GET /integrations/status`
- `GET /integrations/backstage/entities`
- `GET /integrations/netbox/export`
- `POST /integrations/netbox/import`
- `POST /integrations/backstage/sync`
- `GET /integrations/netbox/watermarks`
- `GET /integrations/jobs`
- `GET /integrations/jobs/{jobId}`
- `GET /integrations/schedules`
- `POST /integrations/schedules/{scheduleName}/trigger`

All endpoints except `/health` require service authentication:
- `Authorization: Bearer <service-token>`
- Authentication mode can be configured as `static`, `hybrid`, or `oidc`
- Mutating endpoints are rate-limited per token and route
- Per-endpoint mutating rate limits and payload caps are enforced
- Global request rate limiting is enforced per token/IP and route
- Request bodies and bulk item counts are bounded
- Request processing timeout is enforced with a deterministic timeout response
- API docs are disabled by default (can be explicitly enabled and auth-protected)
- NetBox import supports incremental watermark-based pulls
- Integration sync can run synchronous or as background async jobs (`asyncJob=true`)
- Error responses are normalized and include request correlation IDs

Portal notes:
- `/portal` is publicly reachable but does not expose CMDB data by itself.
- The portal UI requires a valid service token to call secured APIs.

Token scopes:
- `SERVICE_VIEWER_TOKENS`: read-only tokens
- `SERVICE_OPERATOR_TOKENS`: full control tokens
- `SERVICE_APPROVER_TOKENS`: approval decision tokens
- `SERVICE_AUTH_TOKENS`: legacy full control tokens (treated as operator)
- Mutating endpoints require `operator` scope.
- Approval decisions require `approver` scope.
- Optional maker-checker is available for mutating endpoints via `x-cmdb-approval-id`.
- Self-approval is blocked (`requested_by` cannot approve/reject the same request).
- Expired pending approvals are auto-cleaned by the scheduler loop.

Maker-checker flow:
1. Operator creates a pending approval with `POST /approvals`.
2. Approver approves or rejects it with `POST /approvals/{id}/approve` or `/reject`.
3. Operator executes the mutating request with header `x-cmdb-approval-id: <id>`.

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
alembic upgrade head
uvicorn app.main:app --reload
```

Optional for connector scripts:
- `export SERVICE_AUTH_TOKEN=<service-token>`

## OpenAPI

- Swagger UI: `http://localhost:8000/docs`
- OpenAPI JSON: `http://localhost:8000/openapi.json`

## Jira Integration

Jira integration is enabled with environment variables:

- `JIRA_ENABLED=true`
- `JIRA_BASE_URL=https://your-jira.example.com`
- `JIRA_PROJECT_KEY=CMDB`
- `JIRA_EMAIL=<your-atlassian-email>`
- `JIRA_API_TOKEN=<jira-api-token>`

Legacy fallback (non-Atlassian or custom gateway):
- `JIRA_TOKEN=<bearer-token>`

If disabled, issue creation is logged and skipped.

## NetBox And Backstage Glue

Use these environment variables to activate outbound sync webhooks:

- `UNIFIED_CMDB_NAME=unifiedCMDB`
- `SERVICE_AUTH_MODE=static` (`static` | `hybrid` | `oidc`)
- `SERVICE_AUTH_TOKENS=<legacy comma-separated full-control tokens>`
- `SERVICE_OPERATOR_TOKENS=<comma-separated operator tokens>`
- `SERVICE_APPROVER_TOKENS=<comma-separated approver tokens>`
- `SERVICE_VIEWER_TOKENS=<comma-separated viewer tokens>`
- `OIDC_ISSUER=<expected issuer>`
- `OIDC_AUDIENCE=<expected audience>`
- `OIDC_JWKS_URL=<jwks endpoint>`
- `OIDC_ALGORITHMS=RS256`
- `OIDC_SCOPE_VIEWER=cmdb.viewer`
- `OIDC_SCOPE_OPERATOR=cmdb.operator`
- `OIDC_SCOPE_APPROVER=cmdb.approver`
- `API_DOCS_ENABLED=false` (recommended in production)
- `API_DOCS_REQUIRE_AUTH=true` (required if docs are enabled in production)
- `MAX_REQUEST_BODY_BYTES=1048576`
- `MAX_BULK_ITEMS=500`
- `REQUEST_TIMEOUT_SECONDS=30`
- `GLOBAL_RATE_LIMIT_PER_MINUTE=600`
- `MUTATING_RATE_LIMIT_PER_MINUTE=120`
- `MUTATING_RATE_LIMIT_INGEST_PER_MINUTE=60`
- `MUTATING_RATE_LIMIT_INTEGRATIONS_PER_MINUTE=60`
- `MUTATING_RATE_LIMIT_RELATIONSHIPS_PER_MINUTE=90`
- `MUTATING_RATE_LIMIT_CIS_PER_MINUTE=90`
- `MUTATING_RATE_LIMIT_GOVERNANCE_PER_MINUTE=60`
- `MUTATING_RATE_LIMIT_LIFECYCLE_PER_MINUTE=30`
- `MUTATING_RATE_LIMIT_APPROVALS_PER_MINUTE=60`
- `APPROVER_MUTATING_RATE_LIMIT_PER_MINUTE=30`
- `MUTATING_PAYLOAD_LIMIT_DEFAULT_BYTES=65536`
- `MUTATING_PAYLOAD_LIMIT_INGEST_BYTES=1048576`
- `MUTATING_PAYLOAD_LIMIT_INTEGRATIONS_BYTES=8192`
- `MUTATING_PAYLOAD_LIMIT_RELATIONSHIPS_BYTES=16384`
- `MUTATING_PAYLOAD_LIMIT_CIS_BYTES=16384`
- `MUTATING_PAYLOAD_LIMIT_GOVERNANCE_BYTES=8192`
- `MUTATING_PAYLOAD_LIMIT_LIFECYCLE_BYTES=4096`
- `MUTATING_PAYLOAD_LIMIT_APPROVALS_BYTES=65536`
- `MAKER_CHECKER_ENABLED=false`
- `MAKER_CHECKER_DEFAULT_TTL_MINUTES=30`
- `MAKER_CHECKER_BIND_REQUESTER=true`
- `APPROVAL_CLEANUP_INTERVAL_SECONDS=60`
- `DATABASE_URL=postgresql+psycopg://cmdb:cmdb@localhost:5432/cmdb`
- `DATABASE_AUTO_MIGRATE=true`
- `SYNC_JOB_MAX_ATTEMPTS=3`
- `SYNC_JOB_RETRY_BASE_SECONDS=5`
- `SYNC_WORKER_POLL_SECONDS=2`
- `SYNC_SCHEDULER_ENABLED=true`
- `SYNC_SCHEDULE_NETBOX_IMPORT_ENABLED=false`
- `SYNC_SCHEDULE_NETBOX_IMPORT_INTERVAL_SECONDS=900`
- `SYNC_SCHEDULE_NETBOX_IMPORT_LIMIT=500`
- `SYNC_SCHEDULE_BACKSTAGE_SYNC_ENABLED=false`
- `SYNC_SCHEDULE_BACKSTAGE_SYNC_INTERVAL_SECONDS=900`
- `SYNC_SCHEDULE_BACKSTAGE_SYNC_LIMIT=500`
- `NETBOX_SYNC_ENABLED=true`
- `NETBOX_SYNC_URL=https://<netbox-adapter-endpoint>`
- `NETBOX_SYNC_TOKEN=<token>`
- `BACKSTAGE_SYNC_ENABLED=true`
- `BACKSTAGE_SYNC_URL=https://<backstage-base>/api/cmdb`
- `BACKSTAGE_SYNC_TOKEN=<token>`
- `BACKSTAGE_SYNC_SECRET=<legacy-externalAccess secret (base64/base64url)>` (optional alternative to token)
- `BACKSTAGE_CATALOG_URL=https://<backstage-base>/api/catalog`
- `BACKSTAGE_CATALOG_TOKEN=<token>` (optional, used for drift checks)

NetBox pull import configuration:

- `NETBOX_API_URL=https://<netbox-host>` (or `.../api`)
- `NETBOX_API_TOKEN=<Bearer nbt_<key>.<secret> token or raw token>`

In non-dev environments, outbound integration URLs must use `https://`:
- `NETBOX_SYNC_URL`
- `BACKSTAGE_SYNC_URL`
- `NETBOX_API_URL`

Incremental NetBox imports persist watermarks in `sync_state` and can be viewed at:
- `GET /integrations/netbox/watermarks`

If disabled, unifiedCMDB still provides pull-based integration endpoints for both projects.

Backstage source note:

- Backstage CMDB backend write access must allow unifiedCMDB's service subject.
- Add `external:backstage-plugin` under `cmdb.auth.allowedServiceSubjects` in Backstage config.

## Logging

Structured JSON logs are emitted with `correlationId`.
Incoming `x-correlation-id` header is preserved; otherwise one is generated per request.

## Database Migrations And Backup Checks

- Apply schema migrations:
  - `alembic upgrade head`
  - or `./scripts/db_migrate.sh`
- Backup PostgreSQL:
  - `DATABASE_URL=<postgres-url> ./scripts/postgres_backup.sh`
- Backup + restore validation drill:
  - `DATABASE_URL=<source-postgres-url> RESTORE_CHECK_DATABASE_URL=<target-postgres-url> ./scripts/postgres_restore_check.sh`
