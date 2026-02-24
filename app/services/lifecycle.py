from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.time import normalize_utc_naive, utcnow
from app.models import CI, CIStatus, Relationship
from app.services.audit import append_audit_event
from app.services.jira import jira_client

settings = get_settings()


def run_lifecycle(db: Session) -> int:
    now = utcnow()
    transitioned = 0

    cis = list(db.scalars(select(CI)))
    for ci in cis:
        last_seen = normalize_utc_naive(ci.last_seen_at) or ci.last_seen_at
        inactive_days = (now - last_seen).days
        old_status = ci.status

        if inactive_days >= settings.lifecycle_retired_days:
            ci.status = CIStatus.RETIRED
        elif inactive_days >= settings.lifecycle_review_days:
            ci.status = CIStatus.RETIREMENT_REVIEW
        elif inactive_days >= settings.lifecycle_staging_days:
            ci.status = CIStatus.STAGING
        else:
            ci.status = CIStatus.ACTIVE

        if ci.status != old_status:
            transitioned += 1
            append_audit_event(
                db,
                "ci.lifecycle.transitioned",
                {
                    "from": old_status.value,
                    "to": ci.status.value,
                    "inactive_days": inactive_days,
                },
                ci_id=ci.id,
            )

            if ci.status == CIStatus.RETIREMENT_REVIEW:
                jira_client.create_issue(
                    "CI retirement review",
                    {"ci_id": ci.id, "name": ci.name, "inactive_days": inactive_days},
                )

    relationship_pairs = {(rel.source_ci_id, rel.target_ci_id) for rel in db.scalars(select(Relationship))}
    for ci in cis:
        has_rel = any(ci.id in pair for pair in relationship_pairs)
        if not has_rel:
            jira_client.create_issue("Orphan CI detected", {"ci_id": ci.id, "name": ci.name})
            append_audit_event(db, "governance.orphan.detected", {"ci_id": ci.id, "name": ci.name}, ci_id=ci.id)

    db.flush()
    return transitioned
