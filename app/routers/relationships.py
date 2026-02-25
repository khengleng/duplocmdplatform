from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import require_mutation_rate_limit, require_service_auth
from app.models import CI, Relationship
from app.schemas import (
    RelationshipCreateRequest,
    RelationshipRecordResponse,
    RelationshipUpdateRequest,
)
from app.services.audit import append_audit_event

router = APIRouter(prefix="/relationships", tags=["relationships"], dependencies=[Depends(require_service_auth)])


def _to_record(rel: Relationship) -> RelationshipRecordResponse:
    return RelationshipRecordResponse(
        id=rel.id,
        source_ci_id=rel.source_ci_id,
        target_ci_id=rel.target_ci_id,
        relation_type=rel.relation_type,
        source=rel.source,
        created_at=rel.created_at,
    )


@router.get("", response_model=list[RelationshipRecordResponse])
def list_relationships(
    ci_id: str | None = None,
    source_ci_id: str | None = None,
    target_ci_id: str | None = None,
    relation_type: str | None = None,
    limit: int = Query(default=200, ge=1, le=2000),
    db: Session = Depends(get_db),
) -> list[RelationshipRecordResponse]:
    stmt = select(Relationship)
    if ci_id:
        stmt = stmt.where(or_(Relationship.source_ci_id == ci_id, Relationship.target_ci_id == ci_id))
    if source_ci_id:
        stmt = stmt.where(Relationship.source_ci_id == source_ci_id)
    if target_ci_id:
        stmt = stmt.where(Relationship.target_ci_id == target_ci_id)
    if relation_type:
        stmt = stmt.where(Relationship.relation_type == relation_type)
    records = list(db.scalars(stmt.order_by(Relationship.created_at.desc()).limit(limit)))
    return [_to_record(rel) for rel in records]


@router.post("", response_model=RelationshipRecordResponse)
def create_relationship(
    request: RelationshipCreateRequest,
    _rate_limit: None = Depends(require_mutation_rate_limit),
    db: Session = Depends(get_db),
) -> RelationshipRecordResponse:
    source_ci = db.get(CI, request.source_ci_id)
    target_ci = db.get(CI, request.target_ci_id)
    if not source_ci or not target_ci:
        raise HTTPException(status_code=404, detail="Source or target CI not found")

    relationship = Relationship(
        source_ci_id=request.source_ci_id,
        target_ci_id=request.target_ci_id,
        relation_type=request.relation_type,
        source=request.source,
    )
    db.add(relationship)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Relationship already exists") from exc

    append_audit_event(
        db,
        event_type="relationship.updated.manual",
        payload={
            "action": "create",
            "relationship_id": relationship.id,
            "source_ci_id": relationship.source_ci_id,
            "target_ci_id": relationship.target_ci_id,
            "relation_type": relationship.relation_type,
            "source": relationship.source,
        },
        ci_id=relationship.source_ci_id,
    )
    db.commit()
    return _to_record(relationship)


@router.patch("/{relationship_id}", response_model=RelationshipRecordResponse)
def update_relationship(
    relationship_id: int,
    request: RelationshipUpdateRequest,
    _rate_limit: None = Depends(require_mutation_rate_limit),
    db: Session = Depends(get_db),
) -> RelationshipRecordResponse:
    relationship = db.get(Relationship, relationship_id)
    if not relationship:
        raise HTTPException(status_code=404, detail="Relationship not found")

    if request.relation_type:
        relationship.relation_type = request.relation_type
    if request.source:
        relationship.source = request.source

    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Updated relationship conflicts with existing tuple") from exc

    append_audit_event(
        db,
        event_type="relationship.updated.manual",
        payload={
            "action": "update",
            "relationship_id": relationship.id,
            "source_ci_id": relationship.source_ci_id,
            "target_ci_id": relationship.target_ci_id,
            "relation_type": relationship.relation_type,
            "source": relationship.source,
        },
        ci_id=relationship.source_ci_id,
    )
    db.commit()
    return _to_record(relationship)


@router.delete("/{relationship_id}")
def delete_relationship(
    relationship_id: int,
    _rate_limit: None = Depends(require_mutation_rate_limit),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    relationship = db.get(Relationship, relationship_id)
    if not relationship:
        raise HTTPException(status_code=404, detail="Relationship not found")

    append_audit_event(
        db,
        event_type="relationship.updated.manual",
        payload={
            "action": "delete",
            "relationship_id": relationship.id,
            "source_ci_id": relationship.source_ci_id,
            "target_ci_id": relationship.target_ci_id,
            "relation_type": relationship.relation_type,
            "source": relationship.source,
        },
        ci_id=relationship.source_ci_id,
    )
    db.delete(relationship)
    db.commit()
    return {"status": "deleted"}
