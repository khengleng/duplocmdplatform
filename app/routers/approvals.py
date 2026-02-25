from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.core.security import (
    canonical_payload_hash_from_object,
    require_approver_mutation_rate_limit,
    require_mutation_rate_limit,
    require_service_auth,
)
from app.core.time import utcnow
from app.models import ApprovalStatus, ChangeApproval
from app.schemas import ApprovalCreateRequest, ApprovalDecisionRequest, ApprovalResponse
from app.services.approvals import expire_pending_approvals
from app.services.audit import append_audit_event

router = APIRouter(prefix="/approvals", tags=["approvals"], dependencies=[Depends(require_service_auth)])
settings = get_settings()


def _to_response(approval: ChangeApproval) -> ApprovalResponse:
    return ApprovalResponse(
        id=approval.id,
        method=approval.method,
        request_path=approval.request_path,
        payload_hash=approval.payload_hash,
        payload_preview=approval.payload_preview if isinstance(approval.payload_preview, dict) else {},
        reason=approval.reason,
        requested_by=approval.requested_by,
        status=approval.status,
        decided_by=approval.decided_by,
        decision_note=approval.decision_note,
        created_at=approval.created_at,
        expires_at=approval.expires_at,
        decided_at=approval.decided_at,
        consumed_at=approval.consumed_at,
        updated_at=approval.updated_at,
    )


def _normalize_request_path(path: str, query: str | None) -> str:
    normalized_path = path.strip()
    if not normalized_path.startswith("/"):
        raise HTTPException(status_code=400, detail="Approval path must start with '/'")
    if normalized_path.startswith("/approvals"):
        raise HTTPException(status_code=400, detail="Approvals endpoints cannot be self-approved")

    normalized_query = (query or "").strip()
    if normalized_query.startswith("?"):
        normalized_query = normalized_query[1:]
    if not normalized_query:
        return normalized_path
    return f"{normalized_path}?{normalized_query}"


@router.get("", response_model=list[ApprovalResponse])
def list_approvals(
    status: ApprovalStatus | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
    db: Session = Depends(get_db),
) -> list[ApprovalResponse]:
    expired_count = expire_pending_approvals(db)
    if expired_count > 0:
        db.commit()
    stmt = select(ChangeApproval)
    if status:
        stmt = stmt.where(ChangeApproval.status == status)
    records = list(db.scalars(stmt.order_by(ChangeApproval.created_at.desc()).limit(limit)))
    return [_to_response(record) for record in records]


@router.post("", response_model=ApprovalResponse, dependencies=[Depends(require_mutation_rate_limit)])
def create_approval(
    request_body: ApprovalCreateRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> ApprovalResponse:
    expired_count = expire_pending_approvals(db)
    if expired_count > 0:
        db.commit()
    principal = getattr(request.state, "service_principal", "service:unknown")
    request_path = _normalize_request_path(request_body.path, request_body.query)
    payload_hash = canonical_payload_hash_from_object(request_body.payload)

    ttl_minutes = request_body.ttl_minutes or settings.maker_checker_default_ttl_minutes
    expires_at = utcnow() + timedelta(minutes=ttl_minutes)

    approval = ChangeApproval(
        method=request_body.method.upper(),
        request_path=request_path,
        payload_hash=payload_hash,
        payload_preview=request_body.payload if isinstance(request_body.payload, dict) else {},
        reason=request_body.reason.strip() if request_body.reason else None,
        requested_by=principal,
        status=ApprovalStatus.PENDING,
        expires_at=expires_at,
    )
    db.add(approval)
    db.flush()

    append_audit_event(
        db,
        event_type="approval.requested",
        payload={
            "approval_id": approval.id,
            "method": approval.method,
            "request_path": approval.request_path,
            "requested_by": principal,
            "expires_at": approval.expires_at.isoformat(),
        },
    )
    db.commit()
    return _to_response(approval)


@router.post(
    "/{approval_id}/approve",
    response_model=ApprovalResponse,
    dependencies=[Depends(require_approver_mutation_rate_limit)],
)
def approve_approval(
    approval_id: str,
    request_body: ApprovalDecisionRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> ApprovalResponse:
    expired_count = expire_pending_approvals(db)
    if expired_count > 0:
        db.commit()
    approval = db.get(ChangeApproval, approval_id)
    if not approval:
        raise HTTPException(status_code=404, detail="Approval request not found")
    if approval.status != ApprovalStatus.PENDING:
        raise HTTPException(status_code=409, detail="Only PENDING approvals can be approved")
    if approval.expires_at <= utcnow():
        raise HTTPException(status_code=409, detail="Approval request has expired")

    approver = getattr(request.state, "service_principal", "service:unknown")
    if approval.requested_by == approver:
        raise HTTPException(status_code=409, detail="Self-approval is not allowed")
    approval.status = ApprovalStatus.APPROVED
    approval.decided_by = approver
    approval.decision_note = request_body.note.strip() if request_body.note else None
    approval.decided_at = utcnow()
    db.flush()

    append_audit_event(
        db,
        event_type="approval.approved",
        payload={
            "approval_id": approval.id,
            "approved_by": approver,
            "decision_note": approval.decision_note,
        },
    )
    db.commit()
    return _to_response(approval)


@router.post(
    "/{approval_id}/reject",
    response_model=ApprovalResponse,
    dependencies=[Depends(require_approver_mutation_rate_limit)],
)
def reject_approval(
    approval_id: str,
    request_body: ApprovalDecisionRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> ApprovalResponse:
    expired_count = expire_pending_approvals(db)
    if expired_count > 0:
        db.commit()
    approval = db.get(ChangeApproval, approval_id)
    if not approval:
        raise HTTPException(status_code=404, detail="Approval request not found")
    if approval.status != ApprovalStatus.PENDING:
        raise HTTPException(status_code=409, detail="Only PENDING approvals can be rejected")

    approver = getattr(request.state, "service_principal", "service:unknown")
    if approval.requested_by == approver:
        raise HTTPException(status_code=409, detail="Self-decision is not allowed")
    approval.status = ApprovalStatus.REJECTED
    approval.decided_by = approver
    approval.decision_note = request_body.note.strip() if request_body.note else None
    approval.decided_at = utcnow()
    db.flush()

    append_audit_event(
        db,
        event_type="approval.rejected",
        payload={
            "approval_id": approval.id,
            "rejected_by": approver,
            "decision_note": approval.decision_note,
        },
    )
    db.commit()
    return _to_response(approval)
