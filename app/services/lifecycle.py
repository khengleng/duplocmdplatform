"""
Lifecycle management service.

Changes from original:
- CIs are processed in configurable batches (default 1000) to avoid loading
  the entire table into memory.
- Jira notifications (retirement-review, orphan) are deduplicated within a
  single run so the same CI is only notified once per call.
- Jira calls are collected and dispatched *after* db.flush() to avoid blocking
  the write transaction on external HTTP latency.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.time import normalize_utc_naive, utcnow
from app.models import CI, CIStatus, Relationship
from app.services.audit import append_audit_event
from app.services.jira import jira_client

settings = get_settings()

_BATCH_SIZE = 1000


def _process_batch(
    db: Session,
    offset: int,
    relationship_ci_ids: set[str],
    now,
    transitioned: int,
    jira_tasks: list[dict[str, Any]],
    notified_ci_ids: set[str],
) -> tuple[int, list[CI]]:
    """Process one page of CIs and return (transitioned_count, ci_list)."""
    cis = list(db.scalars(select(CI).order_by(CI.id).offset(offset).limit(_BATCH_SIZE)))
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
            # Collect Jira notification — deduped, fired after flush
            if ci.status == CIStatus.RETIREMENT_REVIEW and ci.id not in notified_ci_ids:
                notified_ci_ids.add(ci.id)
                jira_tasks.append({
                    "summary": "CI retirement review",
                    "details": {"ci_id": ci.id, "name": ci.name, "inactive_days": inactive_days},
                })

        # Orphan check — deduped so repeated lifecycle runs don't re-spam Jira
        if ci.id not in relationship_ci_ids and ci.id not in notified_ci_ids:
            notified_ci_ids.add(ci.id)
            append_audit_event(db, "governance.orphan.detected", {"ci_id": ci.id, "name": ci.name}, ci_id=ci.id)
            jira_tasks.append({
                "summary": "Orphan CI detected",
                "details": {"ci_id": ci.id, "name": ci.name},
            })

    return transitioned, cis


def run_lifecycle(db: Session) -> int:
    """
    Run a full lifecycle pass over all CIs.

    Returns the number of CIs whose status was changed.
    Jira issues are created *after* the DB flush to avoid blocking
    writes on external HTTP calls.
    """
    now = utcnow()
    transitioned = 0
    jira_tasks: list[dict[str, Any]] = []
    notified_ci_ids: set[str] = set()   # dedup within this run

    # Build relationship membership set up-front (a single query)
    rel_ci_pair_query = db.execute(select(Relationship.source_ci_id, Relationship.target_ci_id)).all()
    relationship_ci_ids: set[str] = set()
    for src_id, tgt_id in rel_ci_pair_query:
        relationship_ci_ids.add(src_id)
        relationship_ci_ids.add(tgt_id)

    # Fetch total so we know how many batches to run
    total_cis: int = db.scalar(select(func.count()).select_from(CI)) or 0

    offset = 0
    while offset < total_cis:
        transitioned, batch = _process_batch(
            db,
            offset=offset,
            relationship_ci_ids=relationship_ci_ids,
            now=now,
            transitioned=transitioned,
            jira_tasks=jira_tasks,
            notified_ci_ids=notified_ci_ids,
        )
        if not batch:
            break
        # Expire objects to free memory between batches
        for ci in batch:
            db.expunge(ci)
        offset += _BATCH_SIZE

    db.flush()

    # Fire Jira notifications *after* flush — external HTTP should not block writes
    for task in jira_tasks:
        jira_client.create_issue(task["summary"], task["details"])

    return transitioned
