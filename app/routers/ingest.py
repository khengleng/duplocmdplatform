from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.core.security import require_mutation_rate_limit, require_service_auth
from app.models import CI, Identity, Relationship
from app.schemas import (
    CIBulkIngestResult,
    CIPayload,
    RelationshipBulkIngestResult,
    RelationshipPayload,
    RelationshipRef,
)
from app.services.audit import append_audit_event
from app.services.integrations import publish_ci_event
from app.services.reconciliation import reconcile_ci_payload

settings = get_settings()

router = APIRouter(
    prefix="/ingest",
    tags=["ingest"],
    dependencies=[Depends(require_service_auth), Depends(require_mutation_rate_limit)],
)


def _ci_event_payload(ci: CI, source: str) -> dict[str, Any]:
    attributes = ci.attributes if isinstance(ci.attributes, dict) else {}
    return {
        "id": ci.id,
        "ciClass": ci.ci_type,
        "canonicalName": ci.name,
        "environment": attributes.get("environment", "unknown"),
        "lifecycleState": ci.status.value,
        "status": ci.status.value,
        "technicalOwner": ci.owner,
        "supportGroup": attributes.get("support_group"),
        "sourceSystem": source,
        "updatedAt": ci.updated_at.isoformat(),
    }


def _parse_ci_bulk_request(payload: dict[str, Any]) -> tuple[str, list[CIPayload]]:
    source = str(payload.get("source") or payload.get("sourceSystem") or "connector")

    if "cis" in payload:
        raw_items = payload.get("cis")
    elif "items" in payload:
        raw_items = payload.get("items")
    else:
        raise HTTPException(status_code=422, detail="Request must include either 'cis' or 'items'")

    if not isinstance(raw_items, list):
        raise HTTPException(status_code=422, detail="'cis/items' must be a list")
    if len(raw_items) > settings.max_bulk_items:
        raise HTTPException(
            status_code=413,
            detail=f"Too many CI items in a single request (max {settings.max_bulk_items})",
        )

    cis: list[CIPayload] = []
    for raw in raw_items:
        if not isinstance(raw, dict):
            raise HTTPException(status_code=422, detail="Each CI item must be an object")

        try:
            if "ciClass" in raw or "canonicalName" in raw:
                attributes = dict(raw.get("attributes") or {})
                if raw.get("environment") and "environment" not in attributes:
                    attributes["environment"] = raw["environment"]
                if raw.get("lifecycleState") and "lifecycleState" not in attributes:
                    attributes["lifecycleState"] = raw["lifecycleState"]
                if raw.get("supportGroup") and "support_group" not in attributes:
                    attributes["support_group"] = raw["supportGroup"]
                if raw.get("businessOwner") and "businessOwner" not in attributes:
                    attributes["businessOwner"] = raw["businessOwner"]
                if raw.get("criticality") and "criticality" not in attributes:
                    attributes["criticality"] = raw["criticality"]
                if raw.get("costCenter") and "costCenter" not in attributes:
                    attributes["costCenter"] = raw["costCenter"]

                identities = raw.get("identities") or []
                canonical_name = raw.get("canonicalName") or raw.get("name")
                if not identities and canonical_name:
                    identities = [{"scheme": "canonical_name", "value": canonical_name}]

                ci = CIPayload(
                    name=canonical_name,
                    ci_type=raw.get("ciClass") or raw.get("ci_type"),
                    owner=raw.get("technicalOwner") or raw.get("owner") or raw.get("supportGroup"),
                    attributes=attributes,
                    identities=identities,
                )
            else:
                ci = CIPayload.model_validate(raw)
        except ValidationError as exc:
            raise HTTPException(status_code=422, detail=exc.errors()) from exc

        cis.append(ci)

    return source, cis


def _parse_relationship_bulk_request(payload: dict[str, Any]) -> tuple[str, list[RelationshipPayload]]:
    source = str(payload.get("source") or payload.get("sourceSystem") or "connector")

    if "relationships" in payload:
        raw_items = payload.get("relationships")
    elif "items" in payload:
        raw_items = payload.get("items")
    else:
        raise HTTPException(status_code=422, detail="Request must include either 'relationships' or 'items'")

    if not isinstance(raw_items, list):
        raise HTTPException(status_code=422, detail="'relationships/items' must be a list")
    if len(raw_items) > settings.max_bulk_items:
        raise HTTPException(
            status_code=413,
            detail=f"Too many relationship items in a single request (max {settings.max_bulk_items})",
        )

    relationships: list[RelationshipPayload] = []
    for raw in raw_items:
        if not isinstance(raw, dict):
            raise HTTPException(status_code=422, detail="Each relationship item must be an object")

        try:
            if "fromCiId" in raw and "toCiId" in raw:
                relationship = RelationshipPayload(
                    source_ref=RelationshipRef(ci_id=raw.get("fromCiId")),
                    target_ref=RelationshipRef(ci_id=raw.get("toCiId")),
                    relation_type=raw.get("type"),
                )
            else:
                relationship = RelationshipPayload.model_validate(raw)
        except ValidationError as exc:
            raise HTTPException(status_code=422, detail=exc.errors()) from exc

        relationships.append(relationship)

    return source, relationships


@router.post("/cis:bulk", response_model=CIBulkIngestResult)
def ingest_cis_bulk(
    request_body: dict[str, Any],
    dry_run: bool = Query(default=False, alias="dryRun"),
    db: Session = Depends(get_db),
) -> CIBulkIngestResult:
    source, cis = _parse_ci_bulk_request(request_body)

    created = 0
    updated = 0
    collisions = 0
    staged = 0
    events: list[tuple[str, dict[str, Any]]] = []

    try:
        for ci_payload in cis:
            ci, is_created, ci_collisions = reconcile_ci_payload(db, source=source, payload=ci_payload)
            collisions += ci_collisions
            if is_created:
                created += 1
                events.append(("ci.created", _ci_event_payload(ci, source)))
            else:
                updated += 1
                events.append(("ci.updated", _ci_event_payload(ci, source)))

        if dry_run:
            staged = created + updated
            db.rollback()
        else:
            db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Ingest conflict") from exc

    if not dry_run:
        for event_type, event_payload in events:
            publish_ci_event(event_type=event_type, payload=event_payload)

    return CIBulkIngestResult(
        created=created,
        updated=updated,
        collisions=collisions,
        staged=staged,
        errors=[],
    )


def _resolve_ci_ref(db: Session, ci_id: str | None, scheme: str | None, value: str | None) -> CI | None:
    if ci_id:
        return db.get(CI, ci_id)

    if scheme and value:
        stmt = (
            select(CI)
            .join(Identity, Identity.ci_id == CI.id)
            .where(Identity.scheme == scheme, Identity.value == value)
            .limit(1)
        )
        return db.scalar(stmt)

    return None


@router.post("/relationships:bulk", response_model=RelationshipBulkIngestResult)
def ingest_relationships_bulk(
    request_body: dict[str, Any],
    dry_run: bool = Query(default=False, alias="dryRun"),
    db: Session = Depends(get_db),
) -> RelationshipBulkIngestResult:
    source, relationships = _parse_relationship_bulk_request(request_body)

    created = 0
    skipped = 0
    staged = 0
    events: list[tuple[str, dict[str, Any]]] = []

    for rel in relationships:
        src = _resolve_ci_ref(
            db,
            rel.source_ref.ci_id,
            rel.source_ref.identity.scheme if rel.source_ref.identity else None,
            rel.source_ref.identity.value if rel.source_ref.identity else None,
        )
        dst = _resolve_ci_ref(
            db,
            rel.target_ref.ci_id,
            rel.target_ref.identity.scheme if rel.target_ref.identity else None,
            rel.target_ref.identity.value if rel.target_ref.identity else None,
        )

        if not src or not dst:
            skipped += 1
            continue

        exists_stmt = select(Relationship).where(
            Relationship.source_ci_id == src.id,
            Relationship.target_ci_id == dst.id,
            Relationship.relation_type == rel.relation_type,
        )
        if db.scalar(exists_stmt):
            skipped += 1
            continue

        relation = Relationship(
            source_ci_id=src.id,
            target_ci_id=dst.id,
            relation_type=rel.relation_type,
            source=source,
        )
        db.add(relation)
        append_audit_event(
            db,
            "relationship.created",
            {
                "source_ci_id": src.id,
                "target_ci_id": dst.id,
                "relation_type": rel.relation_type,
                "source": source,
            },
            ci_id=src.id,
        )
        events.append(
            (
                "relationship.created",
                {
                    "source_ci_id": src.id,
                    "target_ci_id": dst.id,
                    "relation_type": rel.relation_type,
                    "sourceSystem": source,
                },
            )
        )
        created += 1

    if dry_run:
        staged = created
        db.rollback()
    else:
        db.commit()

    if not dry_run:
        for event_type, event_payload in events:
            publish_ci_event(event_type=event_type, payload=event_payload)

    return RelationshipBulkIngestResult(created=created, skipped=skipped, staged=staged, errors=[])
