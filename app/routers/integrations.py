import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.core.security import require_mutation_rate_limit, require_service_auth
from app.models import CI, Relationship, SyncJob, SyncJobStatus
from app.schemas import (
    CIBulkIngestResult,
    IntegrationJobCreateResponse,
    IntegrationJobResponse,
)
from app.services.integrations import get_netbox_watermarks, run_backstage_sync, run_netbox_import
from app.services.sync_jobs import (
    JOB_TYPE_BACKSTAGE_SYNC,
    JOB_TYPE_NETBOX_IMPORT,
    enqueue_sync_job,
    get_sync_job,
    list_sync_jobs,
)

router = APIRouter(prefix="/integrations", tags=["integrations"], dependencies=[Depends(require_service_auth)])
settings = get_settings()


_slug_re = re.compile(r"[^a-z0-9-]+")


def _slugify(value: str) -> str:
    slug = value.lower().strip().replace(" ", "-")
    slug = _slug_re.sub("-", slug)
    return slug.strip("-") or "ci"


def _job_response(job: SyncJob) -> IntegrationJobResponse:
    return IntegrationJobResponse(
        id=job.id,
        job_type=job.job_type,
        status=job.status,
        requested_by=job.requested_by,
        payload=job.payload,
        result=job.result,
        last_error=job.last_error,
        attempt_count=job.attempt_count,
        max_attempts=job.max_attempts,
        next_run_at=job.next_run_at,
        created_at=job.created_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
    )


@router.get("/status")
def integrations_status(db: Session = Depends(get_db)) -> dict[str, Any]:
    return {
        "unified_cmdb_name": settings.unified_cmdb_name,
        "worker": {
            "sync_job_max_attempts": settings.sync_job_max_attempts,
            "sync_job_retry_base_seconds": settings.sync_job_retry_base_seconds,
            "sync_worker_poll_seconds": settings.sync_worker_poll_seconds,
        },
        "netbox": {
            "enabled": settings.netbox_sync_enabled,
            "configured": bool(settings.netbox_sync_url),
            "api_configured": bool(settings.netbox_api_url and settings.netbox_api_token),
            "watermarks": get_netbox_watermarks(db),
        },
        "backstage": {
            "enabled": settings.backstage_sync_enabled,
            "configured": bool(settings.backstage_sync_url),
            "token_configured": bool(settings.backstage_sync_token),
            "legacy_secret_configured": bool(settings.backstage_sync_secret),
        },
    }


@router.get("/jobs", response_model=list[IntegrationJobResponse])
def list_integration_jobs(
    limit: int = Query(default=50, ge=1, le=200),
    status: SyncJobStatus | None = None,
    db: Session = Depends(get_db),
) -> list[IntegrationJobResponse]:
    jobs = list_sync_jobs(db=db, limit=limit, status=status)
    return [_job_response(job) for job in jobs]


@router.get("/jobs/{job_id}", response_model=IntegrationJobResponse)
def get_integration_job(job_id: str, db: Session = Depends(get_db)) -> IntegrationJobResponse:
    job = get_sync_job(db, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Integration job not found")
    return _job_response(job)


@router.get("/netbox/watermarks")
def netbox_watermarks(db: Session = Depends(get_db)) -> dict[str, Any]:
    return get_netbox_watermarks(db)


@router.get("/backstage/entities")
def backstage_entities(
    limit: int = Query(default=500, ge=1, le=5000),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    cis = list(db.scalars(select(CI).order_by(CI.updated_at.desc()).limit(limit)))

    items = []
    for ci in cis:
        name_slug = _slugify(ci.name)
        items.append(
            {
                "apiVersion": "backstage.io/v1alpha1",
                "kind": "Component",
                "metadata": {
                    "name": f"{name_slug}-{ci.id[:8]}",
                    "title": ci.name,
                    "description": f"CI {ci.id} from {settings.unified_cmdb_name}",
                    "tags": [ci.ci_type.lower(), ci.status.value.lower(), "unifiedcmdb"],
                    "annotations": {
                        "unifiedcmdb.io/ci-id": ci.id,
                        "unifiedcmdb.io/source": ci.source,
                    },
                },
                "spec": {
                    "type": ci.ci_type.lower(),
                    "lifecycle": ci.status.value.lower(),
                    "owner": ci.owner or "group:default/platform-team",
                    "system": settings.unified_cmdb_name,
                },
            }
        )

    return {
        "apiVersion": "v1",
        "kind": "List",
        "items": items,
    }


@router.get("/netbox/export")
def netbox_export(
    limit: int = Query(default=1000, ge=1, le=10000),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    cis = list(db.scalars(select(CI).order_by(CI.updated_at.desc()).limit(limit)))
    relationships = list(db.scalars(select(Relationship)))

    return {
        "source": settings.unified_cmdb_name,
        "cis": [
            {
                "id": ci.id,
                "name": ci.name,
                "ci_type": ci.ci_type,
                "status": ci.status.value,
                "owner": ci.owner,
                "attributes": ci.attributes,
                "source": ci.source,
                "last_seen_at": ci.last_seen_at.isoformat(),
            }
            for ci in cis
        ],
        "relationships": [
            {
                "source_ci_id": rel.source_ci_id,
                "target_ci_id": rel.target_ci_id,
                "relation_type": rel.relation_type,
                "source": rel.source,
            }
            for rel in relationships
        ],
    }


@router.post(
    "/netbox/import",
    response_model=CIBulkIngestResult | IntegrationJobCreateResponse,
    dependencies=[Depends(require_mutation_rate_limit)],
)
def netbox_import(
    request: Request,
    limit: int = Query(default=500, ge=1, le=5000),
    dry_run: bool = Query(default=False, alias="dryRun"),
    incremental: bool = Query(default=True),
    async_job: bool = Query(default=False, alias="asyncJob"),
    db: Session = Depends(get_db),
) -> CIBulkIngestResult | IntegrationJobCreateResponse:
    if limit > settings.max_bulk_items:
        raise HTTPException(
            status_code=400,
            detail=f"Requested limit exceeds configured max_bulk_items ({settings.max_bulk_items})",
        )

    if async_job:
        principal = getattr(request.state, "service_principal", None)
        job = enqueue_sync_job(
            db,
            job_type=JOB_TYPE_NETBOX_IMPORT,
            payload={
                "limit": limit,
                "dry_run": dry_run,
                "incremental": incremental,
            },
            requested_by=principal,
        )
        db.commit()
        return IntegrationJobCreateResponse(
            job_id=job.id,
            job_type=job.job_type,
            status=job.status,
            queued_at=job.created_at,
        )

    try:
        result = run_netbox_import(db, limit=limit, dry_run=dry_run, incremental=incremental)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="NetBox integration is not configured or violates URL policy") from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail="NetBox import failed") from exc

    if dry_run:
        db.rollback()
    else:
        db.commit()

    return CIBulkIngestResult(
        created=result["created"],
        updated=result["updated"],
        collisions=result["collisions"],
        staged=result["staged"],
        errors=result["errors"],
    )


@router.post(
    "/backstage/sync",
    dependencies=[Depends(require_mutation_rate_limit)],
)
def backstage_sync(
    request: Request,
    limit: int = Query(default=500, ge=1, le=5000),
    dry_run: bool = Query(default=False, alias="dryRun"),
    async_job: bool = Query(default=False, alias="asyncJob"),
    db: Session = Depends(get_db),
) -> dict[str, Any] | IntegrationJobCreateResponse:
    if limit > settings.max_bulk_items:
        raise HTTPException(
            status_code=400,
            detail=f"Requested limit exceeds configured max_bulk_items ({settings.max_bulk_items})",
        )

    if async_job:
        principal = getattr(request.state, "service_principal", None)
        job = enqueue_sync_job(
            db,
            job_type=JOB_TYPE_BACKSTAGE_SYNC,
            payload={
                "limit": limit,
                "dry_run": dry_run,
            },
            requested_by=principal,
        )
        db.commit()
        return IntegrationJobCreateResponse(
            job_id=job.id,
            job_type=job.job_type,
            status=job.status,
            queued_at=job.created_at,
        )

    try:
        result = run_backstage_sync(db, limit=limit, dry_run=dry_run)
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Backstage sync failed") from exc

    if dry_run:
        db.rollback()
    else:
        db.commit()
    return result
