from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.time import normalize_utc_naive, utcnow
from app.models import CI, Identity, GovernanceCollision
from app.schemas import CIPayload
from app.services.audit import append_audit_event
from app.services.jira import jira_client


settings = get_settings()


def _source_rank(source: str) -> int:
    try:
        return settings.source_precedence.index(source)
    except ValueError:
        return len(settings.source_precedence)


def _incoming_has_precedence(existing_source: str, incoming_source: str) -> bool:
    return _source_rank(incoming_source) <= _source_rank(existing_source)


def _find_ci_by_identity(db: Session, scheme: str, value: str) -> CI | None:
    stmt = (
        select(CI)
        .join(Identity, Identity.ci_id == CI.id)
        .where(and_(Identity.scheme == scheme, Identity.value == value))
        .limit(1)
    )
    return db.scalar(stmt)


def _create_collision(
    db: Session,
    scheme: str,
    value: str,
    existing_ci_id: str,
    incoming_ci_id: str,
    source: str,
) -> None:
    open_stmt = select(GovernanceCollision).where(
        GovernanceCollision.scheme == scheme,
        GovernanceCollision.value == value,
        GovernanceCollision.existing_ci_id == existing_ci_id,
        GovernanceCollision.incoming_ci_id == incoming_ci_id,
        GovernanceCollision.status == "OPEN",
    )
    existing = db.scalar(open_stmt)
    if existing:
        return

    collision = GovernanceCollision(
        scheme=scheme,
        value=value,
        existing_ci_id=existing_ci_id,
        incoming_ci_id=incoming_ci_id,
    )
    db.add(collision)
    append_audit_event(
        db,
        event_type="governance.collision.detected",
        ci_id=existing_ci_id,
        payload={
            "scheme": scheme,
            "value": value,
            "existing_ci_id": existing_ci_id,
            "incoming_ci_id": incoming_ci_id,
            "source": source,
        },
    )
    jira_client.create_issue(
        summary=f"Identity collision: {scheme}:{value}",
        details={
            "scheme": scheme,
            "value": value,
            "existing_ci_id": existing_ci_id,
            "incoming_ci_id": incoming_ci_id,
            "source": source,
        },
    )


def _ensure_identities(db: Session, ci: CI, payload: CIPayload, source: str) -> int:
    collisions = 0
    for ident in payload.identities:
        stmt = select(Identity).where(Identity.scheme == ident.scheme, Identity.value == ident.value)
        match = db.scalar(stmt)
        if not match:
            db.add(Identity(ci_id=ci.id, scheme=ident.scheme, value=ident.value))
            continue

        if match.ci_id != ci.id:
            _create_collision(
                db,
                scheme=ident.scheme,
                value=ident.value,
                existing_ci_id=match.ci_id,
                incoming_ci_id=ci.id,
                source=source,
            )
            collisions += 1
    return collisions


def reconcile_ci_payload(db: Session, source: str, payload: CIPayload) -> tuple[CI, bool, int]:
    now = normalize_utc_naive(payload.last_seen_at) or utcnow()

    matched_cis: list[CI] = []
    for ident in payload.identities:
        matched = _find_ci_by_identity(db, ident.scheme, ident.value)
        if matched and matched.id not in {ci.id for ci in matched_cis}:
            matched_cis.append(matched)

    if not matched_cis:
        ci = CI(
            name=payload.name,
            ci_type=payload.ci_type,
            source=source,
            owner=payload.owner,
            attributes=payload.attributes,
            last_seen_at=now,
        )
        db.add(ci)
        db.flush()
        collisions = _ensure_identities(db, ci, payload, source)

        append_audit_event(
            db,
            event_type="ci.created",
            ci_id=ci.id,
            payload={"source": source, "identities": [i.model_dump() for i in payload.identities]},
        )
        if not ci.owner:
            jira_client.create_issue("Missing CI ownership", {"ci_id": ci.id, "name": ci.name})
            append_audit_event(db, "governance.owner.missing", {"ci_id": ci.id, "name": ci.name}, ci_id=ci.id)

        return ci, True, collisions

    ci = matched_cis[0]
    collisions = 0
    if len(matched_cis) > 1:
        for conflict in matched_cis[1:]:
            for ident in payload.identities:
                if _find_ci_by_identity(db, ident.scheme, ident.value) and conflict.id != ci.id:
                    _create_collision(
                        db,
                        scheme=ident.scheme,
                        value=ident.value,
                        existing_ci_id=ci.id,
                        incoming_ci_id=conflict.id,
                        source=source,
                    )
                    collisions += 1

    if _incoming_has_precedence(ci.source, source):
        ci.name = payload.name
        ci.ci_type = payload.ci_type
        ci.owner = payload.owner
        ci.attributes = payload.attributes
        ci.source = source
        append_audit_event(db, "ci.updated", {"source": source}, ci_id=ci.id)
    else:
        append_audit_event(
            db,
            "ci.reconcile.skipped_by_precedence",
            {"existing_source": ci.source, "incoming_source": source},
            ci_id=ci.id,
        )

    ci.last_seen_at = now
    collisions += _ensure_identities(db, ci, payload, source)

    if not ci.owner:
        jira_client.create_issue("Missing CI ownership", {"ci_id": ci.id, "name": ci.name})
        append_audit_event(db, "governance.owner.missing", {"ci_id": ci.id, "name": ci.name}, ci_id=ci.id)

    return ci, False, collisions
