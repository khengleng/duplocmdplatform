from datetime import timedelta
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import require_service_auth
from app.core.telemetry import get_alert_snapshot
from app.core.time import utcnow
from app.models import CI, AuditEvent, CollisionStatus, GovernanceCollision, Relationship, SyncJob, SyncJobStatus
from app.schemas import AuthMeResponse
from app.services.integrations import get_netbox_watermarks
from app.services.sync_jobs import list_sync_schedules

router = APIRouter(tags=["dashboard"])
PORTAL_INDEX = Path(__file__).resolve().parents[1] / "static" / "portal" / "index.html"


@router.get("/portal")
def portal() -> FileResponse:
    return FileResponse(PORTAL_INDEX)


@router.get("/dashboard/me", response_model=AuthMeResponse)
def dashboard_me(
    request: Request,
    _token: str = Depends(require_service_auth),
) -> AuthMeResponse:
    principal = getattr(request.state, "service_principal", "service:unknown")
    scope = getattr(request.state, "service_scope", "viewer")
    return AuthMeResponse(principal=principal, scope=scope)


@router.get("/dashboard/summary")
def dashboard_summary(
    _token: str = Depends(require_service_auth),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    total_cis = db.scalar(select(func.count()).select_from(CI)) or 0
    total_relationships = db.scalar(select(func.count()).select_from(Relationship)) or 0
    open_collisions = db.scalar(
        select(func.count()).select_from(GovernanceCollision).where(GovernanceCollision.status == CollisionStatus.OPEN)
    ) or 0

    by_status_rows = db.execute(select(CI.status, func.count()).group_by(CI.status)).all()
    by_source_rows = db.execute(select(CI.source, func.count()).group_by(CI.source)).all()
    by_owner_rows = db.execute(
        select(CI.owner, func.count()).where(CI.owner.is_not(None)).group_by(CI.owner).order_by(func.count().desc()).limit(5)
    ).all()

    by_status = {row[0].value if hasattr(row[0], "value") else str(row[0]): row[1] for row in by_status_rows}
    by_source = {str(row[0]): row[1] for row in by_source_rows}
    top_owners = [{"owner": str(row[0]), "count": row[1]} for row in by_owner_rows if row[0]]

    jobs_total = db.scalar(select(func.count()).select_from(SyncJob)) or 0
    jobs_queued = db.scalar(select(func.count()).select_from(SyncJob).where(SyncJob.status == SyncJobStatus.QUEUED)) or 0
    jobs_running = db.scalar(select(func.count()).select_from(SyncJob).where(SyncJob.status == SyncJobStatus.RUNNING)) or 0
    jobs_failed = db.scalar(select(func.count()).select_from(SyncJob).where(SyncJob.status == SyncJobStatus.FAILED)) or 0

    recent_window = utcnow() - timedelta(hours=24)
    recent_events = db.scalar(select(func.count()).select_from(AuditEvent).where(AuditEvent.created_at >= recent_window)) or 0
    recent_ingest_events = db.scalar(
        select(func.count())
        .select_from(AuditEvent)
        .where(
            AuditEvent.created_at >= recent_window,
            AuditEvent.event_type.in_(["ci.created", "ci.updated", "relationship.created"]),
        )
    ) or 0

    latest_job = db.scalar(select(SyncJob).order_by(SyncJob.created_at.desc()).limit(1))
    latest_job_summary = None
    if latest_job:
        latest_job_summary = {
            "id": latest_job.id,
            "job_type": latest_job.job_type,
            "status": latest_job.status.value,
            "created_at": latest_job.created_at.isoformat(),
            "completed_at": latest_job.completed_at.isoformat() if latest_job.completed_at else None,
            "last_error": latest_job.last_error,
        }

    return {
        "totals": {
            "cis": total_cis,
            "relationships": total_relationships,
            "open_collisions": open_collisions,
            "audit_events_last_24h": recent_events,
            "ingest_events_last_24h": recent_ingest_events,
        },
        "distributions": {
            "by_status": by_status,
            "by_source": by_source,
            "top_owners": top_owners,
        },
        "sync": {
            "jobs_total": jobs_total,
            "jobs_queued": jobs_queued,
            "jobs_running": jobs_running,
            "jobs_failed": jobs_failed,
            "latest_job": latest_job_summary,
            "netbox_watermarks": get_netbox_watermarks(db),
            "schedules": list_sync_schedules(db),
        },
    }


@router.get("/dashboard/activity")
def dashboard_activity(
    limit: int = Query(default=50, ge=1, le=500),
    _token: str = Depends(require_service_auth),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    events = list(db.scalars(select(AuditEvent).order_by(AuditEvent.created_at.desc()).limit(limit)))

    ci_ids = {event.ci_id for event in events if event.ci_id}
    ci_name_map: dict[str, str] = {}
    if ci_ids:
        rows = db.execute(select(CI.id, CI.name).where(CI.id.in_(ci_ids))).all()
        ci_name_map = {row[0]: row[1] for row in rows}

    items = []
    for event in events:
        items.append(
            {
                "id": event.id,
                "ci_id": event.ci_id,
                "ci_name": ci_name_map.get(event.ci_id or "", None),
                "event_type": event.event_type,
                "payload": event.payload,
                "created_at": event.created_at.isoformat(),
            }
        )

    return {"items": items}


@router.get("/dashboard/alerts")
def dashboard_alerts(
    _token: str = Depends(require_service_auth),
) -> dict[str, Any]:
    return get_alert_snapshot()
