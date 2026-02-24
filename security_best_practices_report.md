# Security Best Practices Report

## Executive Summary
The current integration topology is functionally working, but **not secure by default**. The most serious gap is that `cmdb-core` exposes state-changing and integration-triggering endpoints without authentication, which allows unauthenticated internet callers to write CMDB data and drive privileged sync actions into Backstage/NetBox. There are also availability and observability gaps that can be abused for denial-of-service and can hide sync failures.

## Findings

### [F-001] Critical - Unauthenticated state-changing CMDB and integration endpoints
- Location:
  - [/Users/mlh/NetBox-Duplo-CMDB/duplocmdplatform/app/main.py:28](/Users/mlh/NetBox-Duplo-CMDB/duplocmdplatform/app/main.py:28)
  - [/Users/mlh/NetBox-Duplo-CMDB/duplocmdplatform/app/routers/ingest.py:132](/Users/mlh/NetBox-Duplo-CMDB/duplocmdplatform/app/routers/ingest.py:132)
  - [/Users/mlh/NetBox-Duplo-CMDB/duplocmdplatform/app/routers/ingest.py:195](/Users/mlh/NetBox-Duplo-CMDB/duplocmdplatform/app/routers/ingest.py:195)
  - [/Users/mlh/NetBox-Duplo-CMDB/duplocmdplatform/app/routers/integrations.py:121](/Users/mlh/NetBox-Duplo-CMDB/duplocmdplatform/app/routers/integrations.py:121)
  - [/Users/mlh/NetBox-Duplo-CMDB/duplocmdplatform/app/routers/integrations.py:162](/Users/mlh/NetBox-Duplo-CMDB/duplocmdplatform/app/routers/integrations.py:162)
- Evidence:
  - Routers are included globally with no auth dependency/middleware gate.
  - Mutating endpoints (`/ingest/*`, `/integrations/netbox/import`, `/integrations/backstage/sync`) have no caller authentication.
- Impact (critical): Any external caller can modify CMDB state and trigger downstream privileged actions.
- Fix:
  - Add mandatory service authentication (HMAC/JWT/API key with rotation) at router level for all write/sync endpoints.
  - Enforce least-privilege authorization per operation (ingest vs sync vs export).
  - Keep `/health` public, make others authenticated by default.

### [F-002] Critical - Confused deputy: unauthenticated callers can trigger privileged outbound API calls
- Location:
  - [/Users/mlh/NetBox-Duplo-CMDB/duplocmdplatform/app/routers/integrations.py:121](/Users/mlh/NetBox-Duplo-CMDB/duplocmdplatform/app/routers/integrations.py:121)
  - [/Users/mlh/NetBox-Duplo-CMDB/duplocmdplatform/app/routers/integrations.py:162](/Users/mlh/NetBox-Duplo-CMDB/duplocmdplatform/app/routers/integrations.py:162)
  - [/Users/mlh/NetBox-Duplo-CMDB/duplocmdplatform/app/services/integrations.py:35](/Users/mlh/NetBox-Duplo-CMDB/duplocmdplatform/app/services/integrations.py:35)
  - [/Users/mlh/NetBox-Duplo-CMDB/duplocmdplatform/app/services/integrations.py:220](/Users/mlh/NetBox-Duplo-CMDB/duplocmdplatform/app/services/integrations.py:220)
- Evidence:
  - Integration service attaches privileged `Authorization` headers from environment secrets when making outbound calls.
  - Trigger endpoints are unauthenticated.
- Impact (critical): Internet callers can force your service to act with trusted credentials against Backstage/NetBox.
- Fix:
  - Same auth controls as F-001 plus allowlist source IP/network for sync endpoints.
  - Add operation quotas and per-caller rate limits.

### [F-003] High - DoS/flooding risk from unbounded ingest fan-out and synchronous outbound calls
- Location:
  - [/Users/mlh/NetBox-Duplo-CMDB/duplocmdplatform/app/routers/ingest.py:134](/Users/mlh/NetBox-Duplo-CMDB/duplocmdplatform/app/routers/ingest.py:134)
  - [/Users/mlh/NetBox-Duplo-CMDB/duplocmdplatform/app/routers/ingest.py:166](/Users/mlh/NetBox-Duplo-CMDB/duplocmdplatform/app/routers/ingest.py:166)
  - [/Users/mlh/NetBox-Duplo-CMDB/duplocmdplatform/app/services/integrations.py:44](/Users/mlh/NetBox-Duplo-CMDB/duplocmdplatform/app/services/integrations.py:44)
  - [/Users/mlh/NetBox-Duplo-CMDB/duplocmdplatform/app/schemas.py:14](/Users/mlh/NetBox-Duplo-CMDB/duplocmdplatform/app/schemas.py:14)
- Evidence:
  - No hard request-body size guard in FastAPI app or router.
  - No max item count in `cis/items` list.
  - For non-dry-run, each ingested item can trigger outbound sync calls synchronously with 20s timeouts.
- Impact: Attackers can force expensive CPU/DB work and downstream API floods, degrading availability.
- Fix:
  - Add strict `max_items` and field size constraints (Pydantic `max_length`, list bounds).
  - Add ingress body size limits at gateway and app-level validation.
  - Move outbound sync to async queue with worker concurrency + backpressure.

### [F-004] Medium - Internal error detail leakage to clients
- Location:
  - [/Users/mlh/NetBox-Duplo-CMDB/duplocmdplatform/app/routers/ingest.py:164](/Users/mlh/NetBox-Duplo-CMDB/duplocmdplatform/app/routers/ingest.py:164)
  - [/Users/mlh/NetBox-Duplo-CMDB/duplocmdplatform/app/routers/integrations.py:132](/Users/mlh/NetBox-Duplo-CMDB/duplocmdplatform/app/routers/integrations.py:132)
  - [/Users/mlh/NetBox-Duplo-CMDB/duplocmdplatform/app/services/integrations.py:49](/Users/mlh/NetBox-Duplo-CMDB/duplocmdplatform/app/services/integrations.py:49)
- Evidence:
  - API responses include raw exception text (`exc.orig`, `str(exc)`), which can expose schema/internal dependency details.
- Impact: Increases attacker reconnaissance capability.
- Fix:
  - Return generic client-safe messages and error codes.
  - Keep detailed exception context only in structured logs.

### [F-005] Medium - Backstage CMDB read endpoints rely on external/global auth behavior (no explicit route-level auth checks)
- Location:
  - [/Users/mlh/duplo/duplo/backstage/plugins/cmdb-backend/src/service/router.ts:121](/Users/mlh/duplo/duplo/backstage/plugins/cmdb-backend/src/service/router.ts:121)
  - [/Users/mlh/duplo/duplo/backstage/plugins/cmdb-backend/src/service/router.ts:138](/Users/mlh/duplo/duplo/backstage/plugins/cmdb-backend/src/service/router.ts:138)
- Evidence:
  - `GET /cis` and `GET /cis/:id` do not invoke route-level `getWriteCredentials`/role checks.
- Impact: If platform-level auth policy changes, these routes may become unintentionally exposed.
- Fix:
  - Add explicit read-access policy checks (service/user role gating) or document/enforce this dependency with tests.

## Stability Notes
- Attribute serialization write-path in Backstage CMDB was patched to safely persist primitive JSON values:
  - [/Users/mlh/duplo/duplo/backstage/plugins/cmdb-backend/src/database/CmdbStore.ts:1041](/Users/mlh/duplo/duplo/backstage/plugins/cmdb-backend/src/database/CmdbStore.ts:1041)
- `cmdb-core` outbound payload now includes `attributes` again:
  - [/Users/mlh/NetBox-Duplo-CMDB/duplocmdplatform/app/services/integrations.py:129](/Users/mlh/NetBox-Duplo-CMDB/duplocmdplatform/app/services/integrations.py:129)

## Recommended Remediation Order
1. Implement mandatory authN/authZ for all mutating/sync endpoints (F-001/F-002).
2. Add rate limits, request caps, and async queueing for outbound sync fan-out (F-003).
3. Remove raw exception leakage from HTTP responses (F-004).
4. Add explicit read-access checks in Backstage router for defense in depth (F-005).
