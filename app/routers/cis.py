from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import require_mutation_rate_limit, require_service_auth
from app.models import CI, AuditEvent, Identity, Relationship
from app.schemas import (
    AuditEventResponse,
    CIDetailResponse,
    CIDriftResolveRequest,
    CIDriftResolveResponse,
    CIDriftResponse,
    CIGraphResponse,
    CIResponse,
    IdentityResponse,
    PaginatedCIResponse,
    PickerCIResponse,
    RelationshipResponse,
)
from app.services.audit import append_audit_event
from app.services.drift import compute_ci_drift

router = APIRouter(tags=["cis"], dependencies=[Depends(require_service_auth)])
RESOLVABLE_CI_FIELDS = {"name", "ci_type", "owner"}


def _to_ci_response(ci: CI) -> CIResponse:
    environment = ci.attributes.get("environment") if isinstance(ci.attributes, dict) else None
    support_group = ci.attributes.get("support_group") if isinstance(ci.attributes, dict) else None
    return CIResponse(
        id=ci.id,
        name=ci.name,
        ci_type=ci.ci_type,
        source=ci.source,
        owner=ci.owner,
        status=ci.status,
        attributes=ci.attributes,
        last_seen_at=ci.last_seen_at,
        created_at=ci.created_at,
        updated_at=ci.updated_at,
        ciClass=ci.ci_type,
        canonicalName=ci.name,
        environment=environment or "unknown",
        lifecycleState=ci.status.value,
        technicalOwner=ci.owner,
        supportGroup=support_group,
        updatedAt=ci.updated_at,
    )


def _to_rel_response(rel: Relationship) -> RelationshipResponse:
    return RelationshipResponse(
        source_ci_id=rel.source_ci_id,
        target_ci_id=rel.target_ci_id,
        relation_type=rel.relation_type,
        source=rel.source,
    )


@router.get("/cis", response_model=PaginatedCIResponse)
def list_cis(
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    status: str | None = None,
    source: str | None = None,
    owner: str | None = None,
    environment: str | None = None,
    ciClass: str | None = None,
    lifecycleState: str | None = None,
    q: str | None = None,
    db: Session = Depends(get_db),
) -> PaginatedCIResponse:
    stmt = select(CI)

    if status:
        stmt = stmt.where(CI.status == status)
    if source:
        stmt = stmt.where(CI.source == source)
    if owner:
        stmt = stmt.where(CI.owner == owner)
    if environment:
        stmt = stmt.where(CI.attributes["environment"].as_string() == environment)
    if ciClass:
        stmt = stmt.where(CI.ci_type == ciClass)
    if lifecycleState:
        stmt = stmt.where(CI.status == lifecycleState)
    if q:
        stmt = stmt.where(or_(CI.name.ilike(f"%{q}%"), CI.ci_type.ilike(f"%{q}%")))

    total_stmt = select(func.count()).select_from(stmt.subquery())
    total = db.scalar(total_stmt) or 0

    items = list(db.scalars(stmt.order_by(CI.updated_at.desc()).offset(offset).limit(limit)))
    return PaginatedCIResponse(total=total, items=[_to_ci_response(item) for item in items])


@router.get("/cis/{ci_id}", response_model=CIResponse)
def get_ci(ci_id: str, db: Session = Depends(get_db)) -> CIResponse:
    ci = db.get(CI, ci_id)
    if not ci:
        raise HTTPException(status_code=404, detail="CI not found")
    return _to_ci_response(ci)


@router.get("/cis/{ci_id}/graph", response_model=CIGraphResponse)
def get_ci_graph(ci_id: str, db: Session = Depends(get_db)) -> CIGraphResponse:
    ci = db.get(CI, ci_id)
    if not ci:
        raise HTTPException(status_code=404, detail="CI not found")

    upstream = list(db.scalars(select(Relationship).where(Relationship.target_ci_id == ci_id)))
    downstream = list(db.scalars(select(Relationship).where(Relationship.source_ci_id == ci_id)))

    return CIGraphResponse(
        ci=_to_ci_response(ci),
        upstream=[_to_rel_response(rel) for rel in upstream],
        downstream=[_to_rel_response(rel) for rel in downstream],
    )


@router.get("/cis/{ci_id}/audit", response_model=list[AuditEventResponse])
def get_ci_audit(
    ci_id: str,
    limit: int = Query(default=100, ge=1, le=5000),
    db: Session = Depends(get_db),
) -> list[AuditEventResponse]:
    ci = db.get(CI, ci_id)
    if not ci:
        raise HTTPException(status_code=404, detail="CI not found")

    events = list(
        db.scalars(
            select(AuditEvent).where(AuditEvent.ci_id == ci_id).order_by(AuditEvent.created_at.desc()).limit(limit)
        )
    )
    return [
        AuditEventResponse(
            id=event.id,
            ci_id=event.ci_id,
            event_type=event.event_type,
            payload=event.payload,
            created_at=event.created_at,
        )
        for event in events
    ]


@router.get("/cis/{ci_id}/identities", response_model=list[IdentityResponse])
def get_ci_identities(ci_id: str, db: Session = Depends(get_db)) -> list[IdentityResponse]:
    ci = db.get(CI, ci_id)
    if not ci:
        raise HTTPException(status_code=404, detail="CI not found")

    identities = list(db.scalars(select(Identity).where(Identity.ci_id == ci_id).order_by(Identity.created_at.asc())))
    return [
        IdentityResponse(
            scheme=identity.scheme,
            value=identity.value,
            created_at=identity.created_at,
        )
        for identity in identities
    ]


@router.get("/cis/{ci_id}/detail", response_model=CIDetailResponse)
def get_ci_detail(ci_id: str, db: Session = Depends(get_db)) -> CIDetailResponse:
    ci = db.get(CI, ci_id)
    if not ci:
        raise HTTPException(status_code=404, detail="CI not found")

    identities = list(db.scalars(select(Identity).where(Identity.ci_id == ci_id).order_by(Identity.created_at.asc())))
    upstream = list(db.scalars(select(Relationship).where(Relationship.target_ci_id == ci_id)))
    downstream = list(db.scalars(select(Relationship).where(Relationship.source_ci_id == ci_id)))
    events = list(
        db.scalars(select(AuditEvent).where(AuditEvent.ci_id == ci_id).order_by(AuditEvent.created_at.desc()).limit(50))
    )

    return CIDetailResponse(
        ci=_to_ci_response(ci),
        identities=[
            IdentityResponse(
                scheme=identity.scheme,
                value=identity.value,
                created_at=identity.created_at,
            )
            for identity in identities
        ],
        upstream=[_to_rel_response(rel) for rel in upstream],
        downstream=[_to_rel_response(rel) for rel in downstream],
        recent_audit=[
            AuditEventResponse(
                id=event.id,
                ci_id=event.ci_id,
                event_type=event.event_type,
                payload=event.payload,
                created_at=event.created_at,
            )
            for event in events
        ],
    )


@router.get("/cis/{ci_id}/drift", response_model=CIDriftResponse)
def get_ci_drift(ci_id: str, db: Session = Depends(get_db)) -> CIDriftResponse:
    ci = db.get(CI, ci_id)
    if not ci:
        raise HTTPException(status_code=404, detail="CI not found")
    drift = compute_ci_drift(db, ci)
    return CIDriftResponse(**drift)


@router.post(
    "/cis/{ci_id}/drift/resolve",
    response_model=CIDriftResolveResponse,
    dependencies=[Depends(require_mutation_rate_limit)],
)
def resolve_ci_drift(
    ci_id: str,
    request_body: CIDriftResolveRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> CIDriftResolveResponse:
    ci = db.get(CI, ci_id)
    if not ci:
        raise HTTPException(status_code=404, detail="CI not found")

    requested_fields = [field for field in request_body.fields if field]
    if not requested_fields:
        raise HTTPException(status_code=400, detail="At least one field must be selected for drift resolution")

    principal = getattr(request.state, "service_principal", "service:unknown")
    drift_snapshot = compute_ci_drift(db, ci)

    ignored_fields: list[str] = []
    applied: dict[str, dict[str, str | None]] = {}
    selected_source = request_body.source

    if selected_source == "cmdb":
        ignored_fields = requested_fields
    else:
        source_state = drift_snapshot.get(selected_source)
        if not isinstance(source_state, dict):
            raise HTTPException(status_code=400, detail="Drift source payload is unavailable")
        source_status = source_state.get("status")
        if source_status in {"unavailable", "error", "missing", "not_applicable"}:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot resolve from {selected_source} because source status is {source_status}",
            )

        source_target = source_state.get("target")
        if not isinstance(source_target, dict):
            raise HTTPException(status_code=400, detail=f"{selected_source} drift target is unavailable")

        for field in requested_fields:
            if field not in RESOLVABLE_CI_FIELDS:
                ignored_fields.append(field)
                continue

            incoming_value = source_target.get(field)
            if incoming_value is None:
                ignored_fields.append(field)
                continue

            existing_value = getattr(ci, field)
            coerced_incoming = str(incoming_value)
            if existing_value != coerced_incoming:
                setattr(ci, field, coerced_incoming)
                applied[field] = {"before": existing_value, "after": coerced_incoming}

        if applied:
            ci.source = selected_source

    append_audit_event(
        db,
        event_type="ci.drift.resolved",
        payload={
            "ci_id": ci.id,
            "source": selected_source,
            "requested_fields": requested_fields,
            "applied": applied,
            "ignored_fields": ignored_fields,
            "requested_by": principal,
        },
        ci_id=ci.id,
    )
    db.commit()

    refreshed_drift = compute_ci_drift(db, ci)
    return CIDriftResolveResponse(
        ci_id=ci.id,
        source=selected_source,
        applied=applied,
        ignored_fields=ignored_fields,
        drift=CIDriftResponse(**refreshed_drift),
    )


@router.get("/pickers/cis", response_model=list[PickerCIResponse])
def pick_cis(
    q: str | None = None,
    limit: int = Query(default=20, ge=1, le=200),
    db: Session = Depends(get_db),
) -> list[PickerCIResponse]:
    stmt = select(CI)
    if q:
        stmt = stmt.where(or_(CI.name.ilike(f"%{q}%"), CI.ci_type.ilike(f"%{q}%")))

    items = list(db.scalars(stmt.order_by(CI.name.asc()).limit(limit)))
    return [PickerCIResponse(id=item.id, name=item.name, ci_type=item.ci_type, status=item.status) for item in items]
