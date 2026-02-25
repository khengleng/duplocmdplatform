from datetime import datetime
from typing import Literal
from typing import Any

from pydantic import BaseModel, Field

from app.models import ApprovalStatus, CIStatus, CollisionStatus, SyncJobStatus


class IdentityPayload(BaseModel):
    scheme: str
    value: str


class IdentityResponse(BaseModel):
    scheme: str
    value: str
    created_at: datetime


class CIPayload(BaseModel):
    name: str
    ci_type: str
    owner: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)
    identities: list[IdentityPayload]
    last_seen_at: datetime | None = None


class CIBulkIngestRequest(BaseModel):
    source: str
    cis: list[CIPayload]


class CIBulkIngestResult(BaseModel):
    created: int
    updated: int
    collisions: int
    staged: int = 0
    errors: list[dict[str, Any]] = Field(default_factory=list)


class RelationshipRef(BaseModel):
    ci_id: str | None = None
    identity: IdentityPayload | None = None


class RelationshipPayload(BaseModel):
    source_ref: RelationshipRef
    target_ref: RelationshipRef
    relation_type: str


class RelationshipBulkIngestRequest(BaseModel):
    source: str
    relationships: list[RelationshipPayload]


class RelationshipBulkIngestResult(BaseModel):
    created: int
    skipped: int
    staged: int = 0
    errors: list[dict[str, Any]] = Field(default_factory=list)


class CIResponse(BaseModel):
    id: str
    name: str
    ci_type: str
    source: str
    owner: str | None
    status: CIStatus
    attributes: dict[str, Any]
    last_seen_at: datetime
    created_at: datetime
    updated_at: datetime
    ciClass: str | None = None
    canonicalName: str | None = None
    environment: str | None = None
    lifecycleState: str | None = None
    technicalOwner: str | None = None
    supportGroup: str | None = None
    updatedAt: datetime | None = None


class PaginatedCIResponse(BaseModel):
    total: int
    items: list[CIResponse]


class RelationshipResponse(BaseModel):
    source_ci_id: str
    target_ci_id: str
    relation_type: str
    source: str


class RelationshipRecordResponse(RelationshipResponse):
    id: int
    created_at: datetime


class RelationshipCreateRequest(BaseModel):
    source_ci_id: str
    target_ci_id: str
    relation_type: str
    source: str = "manual"


class RelationshipUpdateRequest(BaseModel):
    relation_type: str | None = None
    source: str | None = None


class CIGraphResponse(BaseModel):
    ci: CIResponse
    upstream: list[RelationshipResponse]
    downstream: list[RelationshipResponse]


class AuditEventResponse(BaseModel):
    id: int
    ci_id: str | None
    event_type: str
    payload: dict[str, Any]
    created_at: datetime


class PickerCIResponse(BaseModel):
    id: str
    name: str
    ci_type: str
    status: CIStatus


class CollisionResolveRequest(BaseModel):
    resolution_note: str


class CollisionReopenRequest(BaseModel):
    reopen_note: str


class CollisionResponse(BaseModel):
    id: int
    scheme: str
    value: str
    existing_ci_id: str
    incoming_ci_id: str
    status: CollisionStatus
    resolution_note: str | None
    resolved_at: datetime | None
    created_at: datetime


class CollisionResolveResponse(BaseModel):
    collision: CollisionResponse


class LifecycleRunResponse(BaseModel):
    transitioned: int


class HealthResponse(BaseModel):
    status: str = "ok"


class CIDetailResponse(BaseModel):
    ci: CIResponse
    identities: list[IdentityResponse]
    upstream: list[RelationshipResponse]
    downstream: list[RelationshipResponse]
    recent_audit: list[AuditEventResponse]


class CIDriftResponse(BaseModel):
    ci_id: str
    overall_status: str
    cmdb: dict[str, Any]
    netbox: dict[str, Any]
    backstage: dict[str, Any]


class CIDriftResolveRequest(BaseModel):
    source: Literal["cmdb", "netbox", "backstage"] = "netbox"
    fields: list[str] = Field(default_factory=lambda: ["name", "ci_type", "owner"])


class CIDriftResolveResponse(BaseModel):
    ci_id: str
    source: str
    applied: dict[str, dict[str, Any]]
    ignored_fields: list[str]
    drift: CIDriftResponse


class ApprovalCreateRequest(BaseModel):
    method: Literal["POST", "PUT", "PATCH", "DELETE"]
    path: str
    query: str | None = None
    payload: Any | None = None
    reason: str | None = None
    ttl_minutes: int = Field(default=30, ge=1, le=1440)


class ApprovalDecisionRequest(BaseModel):
    note: str | None = None


class ApprovalResponse(BaseModel):
    id: str
    method: str
    request_path: str
    payload_hash: str
    payload_preview: dict[str, Any]
    reason: str | None
    requested_by: str
    status: ApprovalStatus
    decided_by: str | None
    decision_note: str | None
    created_at: datetime
    expires_at: datetime
    decided_at: datetime | None
    consumed_at: datetime | None
    updated_at: datetime


class AuthMeResponse(BaseModel):
    principal: str
    scope: str


class IntegrationJobCreateResponse(BaseModel):
    job_id: str
    job_type: str
    status: SyncJobStatus
    queued_at: datetime


class IntegrationJobResponse(BaseModel):
    id: str
    job_type: str
    status: SyncJobStatus
    requested_by: str | None = None
    payload: dict[str, Any]
    result: dict[str, Any] | None = None
    last_error: str | None = None
    attempt_count: int
    max_attempts: int
    next_run_at: datetime
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
