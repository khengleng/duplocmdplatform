# Security Best Practices Report

## Executive Summary
Mutating endpoints are now significantly hardened (service auth, route-level rate limiting, bulk caps, and safer error responses). I did not find hardcoded credentials, embedded shell execution payloads, or obvious code-injection backdoors. Remaining risks are mainly around data exposure and availability hardening.

## Findings

### [F-001] High - Unauthenticated read endpoints expose full CMDB and audit data
- Location:
  - [/Users/mlh/NetBox-Duplo-CMDB/duplocmdplatform/app/routers/cis.py:52](/Users/mlh/NetBox-Duplo-CMDB/duplocmdplatform/app/routers/cis.py:52)
  - [/Users/mlh/NetBox-Duplo-CMDB/duplocmdplatform/app/routers/cis.py:113](/Users/mlh/NetBox-Duplo-CMDB/duplocmdplatform/app/routers/cis.py:113)
  - [/Users/mlh/NetBox-Duplo-CMDB/duplocmdplatform/app/routers/audit.py:13](/Users/mlh/NetBox-Duplo-CMDB/duplocmdplatform/app/routers/audit.py:13)
  - [/Users/mlh/NetBox-Duplo-CMDB/duplocmdplatform/app/routers/integrations.py:47](/Users/mlh/NetBox-Duplo-CMDB/duplocmdplatform/app/routers/integrations.py:47)
  - [/Users/mlh/NetBox-Duplo-CMDB/duplocmdplatform/app/routers/integrations.py:87](/Users/mlh/NetBox-Duplo-CMDB/duplocmdplatform/app/routers/integrations.py:87)
- Evidence:
  - These routes are public and return CI inventory, relationships, and audit payloads.
  - No `Depends(require_service_auth)` on these read endpoints.
- Impact:
  - Any unauthenticated caller can enumerate topology, ownership, and operational metadata.
- Recommendation:
  - Require auth on read APIs too, or enforce strict network ACLs.
  - Consider separate read scopes from write scopes.

### [F-002] High - Request-size middleware still buffers full body in memory
- Location:
  - [/Users/mlh/NetBox-Duplo-CMDB/duplocmdplatform/app/main.py:21](/Users/mlh/NetBox-Duplo-CMDB/duplocmdplatform/app/main.py:21)
  - [/Users/mlh/NetBox-Duplo-CMDB/duplocmdplatform/app/main.py:33](/Users/mlh/NetBox-Duplo-CMDB/duplocmdplatform/app/main.py:33)
- Evidence:
  - `await request.body()` reads the full payload before rejecting by size.
  - Attackers can omit or spoof `Content-Length` and still force large in-memory reads.
- Impact:
  - Memory-exhaustion DoS remains possible at app layer.
- Recommendation:
  - Enforce hard body limits at edge proxy/load balancer first.
  - For app-level handling, reject mutating requests with missing/invalid `Content-Length` instead of full buffering.

### [F-003] Medium - Production API docs are exposed by default
- Location:
  - [/Users/mlh/NetBox-Duplo-CMDB/duplocmdplatform/app/main.py:16](/Users/mlh/NetBox-Duplo-CMDB/duplocmdplatform/app/main.py:16)
  - [/Users/mlh/NetBox-Duplo-CMDB/duplocmdplatform/README.md:87](/Users/mlh/NetBox-Duplo-CMDB/duplocmdplatform/README.md:87)
- Evidence:
  - FastAPI is initialized without disabling `docs_url` / `redoc_url` / `openapi_url`.
- Impact:
  - Endpoint and schema discovery is easier for attackers.
- Recommendation:
  - Disable or protect docs in production (`docs_url=None`, `redoc_url=None`, `openapi_url=None`), controlled by env.

### [F-004] Medium - Outbound sync and NetBox pull URLs are not restricted to HTTPS
- Location:
  - [/Users/mlh/NetBox-Duplo-CMDB/duplocmdplatform/app/services/integrations.py:44](/Users/mlh/NetBox-Duplo-CMDB/duplocmdplatform/app/services/integrations.py:44)
  - [/Users/mlh/NetBox-Duplo-CMDB/duplocmdplatform/app/services/integrations.py:267](/Users/mlh/NetBox-Duplo-CMDB/duplocmdplatform/app/services/integrations.py:267)
- Evidence:
  - Outbound requests accept environment-provided URLs without scheme enforcement.
- Impact:
  - Misconfiguration to `http://` can leak bearer tokens and payloads in transit.
- Recommendation:
  - Validate configured integration URLs and require `https://` in non-dev environments.

### [F-005] Medium - Jira failures can break ingest/lifecycle operations when enabled
- Location:
  - [/Users/mlh/NetBox-Duplo-CMDB/duplocmdplatform/app/services/jira.py:34](/Users/mlh/NetBox-Duplo-CMDB/duplocmdplatform/app/services/jira.py:34)
  - [/Users/mlh/NetBox-Duplo-CMDB/duplocmdplatform/app/services/reconciliation.py:74](/Users/mlh/NetBox-Duplo-CMDB/duplocmdplatform/app/services/reconciliation.py:74)
  - [/Users/mlh/NetBox-Duplo-CMDB/duplocmdplatform/app/services/lifecycle.py:46](/Users/mlh/NetBox-Duplo-CMDB/duplocmdplatform/app/services/lifecycle.py:46)
- Evidence:
  - `JiraClient.create_issue` raises on HTTP errors and callers do not isolate failures.
- Impact:
  - External Jira outage can degrade or fail core CMDB processing paths.
- Recommendation:
  - Catch Jira errors in caller paths, log them, and continue core transaction.
  - Consider async fire-and-forget queueing for ticket creation.

## Hardcoded Secret Review
- No hardcoded API keys/private keys/tokens found in repository source files or `.env.example`.
- No `eval`, `exec`, `os.system`, or unsafe `pickle/yaml.load` patterns found in application code.

## Recommended Remediation Order
1. Protect read endpoints with auth and/or network controls (F-001).
2. Move body-size enforcement to edge and hard-fail missing `Content-Length` for mutating routes (F-002).
3. Disable or protect OpenAPI docs in production (F-003).
4. Enforce HTTPS-only outbound integration URLs in production (F-004).
5. Make Jira integration non-blocking for core ingest/lifecycle paths (F-005).
