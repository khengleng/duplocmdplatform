# Unified CMDB Bank-Grade Backlog

## Scope
This backlog defines the remaining features and controls required to operate the Unified CMDB platform as a production system for a bank.

## Release Plan
- Phase P0: Security and resilience gates for production entry.
- Phase P1: Core CMDB governance and operational completeness.
- Phase P2: Ecosystem integrations and optimization.

## P0 Epics (Production Entry)

### P0-E01 Enterprise Authentication and Access Control
Goal: move from static service tokens toward enterprise identity and controlled operations.

Stories:
- P0-S01: Integrate OIDC service auth for machine-to-machine API access.
- P0-S02: Add token issuer/audience validation and key rotation support (JWKS).
- P0-S03: Enforce role-based scopes (`viewer`, `operator`, `approver`) per endpoint.
- P0-S04: Add maker-checker workflow for mutating operations.

Acceptance:
- All mutating APIs require operator scope.
- High-impact operations require explicit approval state before execution.
- Access decisions are logged to audit events.

### P0-E02 DoS and Runtime Protection
Goal: enforce bounded resource usage across all requests.

Stories:
- P0-S05: Add global API request rate limiting (per token/IP + route).
- P0-S06: Keep strict mutating endpoint rate limits.
- P0-S07: Enforce request body size bounds and bulk bounds.
- P0-S08: Add request processing timeout and uniform timeout response.

Acceptance:
- Saturation tests show bounded request throughput without service crash.
- Exceeded bounds produce deterministic `429`/`413`/`504` responses.

### P0-E03 Secure Error Handling and Audit Integrity
Goal: prevent internal detail leakage and improve traceability.

Stories:
- P0-S09: Standardize API error schema with request IDs.
- P0-S10: Return generic messages for `5xx` responses.
- P0-S11: Keep append-only audit trail with export and documented retention policy.
- P0-S12: Add alerting hooks for repeated `5xx`, `429`, and sync failures.

Acceptance:
- No stack traces or internal internals returned to clients.
- Every error response includes request correlation ID.

### P0-E04 Platform Reliability Baseline
Goal: achieve operational baseline required by regulated environments.

Stories:
- P0-S13: Postgres production profile with backup/restore runbook.
- P0-S14: Health/readiness checks and deployment rollback procedure.
- P0-S15: SLOs and dashboards for API availability and sync freshness.

Acceptance:
- Restore drill completes in documented RTO/RPO target.
- On-call runbook supports degraded mode and rollback.

## P1 Epics (CMDB Completeness)

### P1-E01 Data Model Governance
Stories:
- P1-S01: Canonical CI class taxonomy and mandatory field rules.
- P1-S02: Data quality scoring and stewardship queue.
- P1-S03: Field-level provenance per CI attribute.

### P1-E02 Dependency and Impact Intelligence
Stories:
- P1-S04: Relationship validation rules (allowed edge matrix).
- P1-S05: Impact analysis graph traversal for incident/change planning.
- P1-S06: Relationship confidence scoring and stale-edge detection.

### P1-E03 Change Governance
Stories:
- P1-S07: Baseline snapshots and CI version history.
- P1-S08: Policy-controlled lifecycle transitions with exceptions.
- P1-S09: Compliance evidence export package templates.

## P2 Epics (Integration Expansion)

### P2-E01 NetBox Deep Integration
Stories:
- P2-S01: Sync interfaces, IP addresses, prefixes, VLANs, racks, sites.
- P2-S02: Bi-directional reconciliation policy by field ownership.

### P2-E02 Backstage and ITSM Process Integration
Stories:
- P2-S03: Backstage writeback conflict policy and approval path.
- P2-S04: Jira/ITSM linkage for change, incident, and CMDB evidence trails.

### P2-E03 Event-Driven Scale
Stories:
- P2-S05: Event bus ingestion with idempotency keys and replay.
- P2-S06: Dead-letter queues and retry observability.

## Current Sprint (Started)
- IN PROGRESS: P0-S05 global API request rate limiting.
- IN PROGRESS: P0-S08 request timeout enforcement.
- IN PROGRESS: P0-S09 and P0-S10 standardized sanitized error responses.

