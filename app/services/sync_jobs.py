import logging
import threading
from datetime import timedelta
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.core.time import utcnow
from app.models import SyncJob, SyncJobStatus
from app.services.audit import append_audit_event
from app.services.integrations import run_backstage_sync, run_netbox_import

logger = logging.getLogger(__name__)
settings = get_settings()

JOB_TYPE_NETBOX_IMPORT = "netbox.import"
JOB_TYPE_BACKSTAGE_SYNC = "backstage.sync"

_worker_lock = threading.Lock()
_worker_thread: threading.Thread | None = None
_worker_stop_event = threading.Event()


def enqueue_sync_job(
    db: Session,
    *,
    job_type: str,
    payload: dict[str, Any],
    requested_by: str | None = None,
    max_attempts: int | None = None,
) -> SyncJob:
    max_tries = max_attempts if max_attempts is not None else settings.sync_job_max_attempts
    job = SyncJob(
        job_type=job_type,
        status=SyncJobStatus.QUEUED,
        requested_by=requested_by,
        payload=payload,
        max_attempts=max(1, max_tries),
        next_run_at=utcnow(),
    )
    db.add(job)
    db.flush()
    append_audit_event(
        db,
        event_type="integration.job.queued",
        payload={
            "job_id": job.id,
            "job_type": job.job_type,
            "requested_by": requested_by,
            "payload": payload,
        },
    )
    return job


def get_sync_job(db: Session, job_id: str) -> SyncJob | None:
    return db.get(SyncJob, job_id)


def list_sync_jobs(db: Session, limit: int = 50, status: SyncJobStatus | None = None) -> list[SyncJob]:
    stmt = select(SyncJob)
    if status is not None:
        stmt = stmt.where(SyncJob.status == status)
    stmt = stmt.order_by(SyncJob.created_at.desc()).limit(limit)
    return list(db.scalars(stmt))


def _retry_delay_seconds(attempt_count: int) -> int:
    base = max(1, settings.sync_job_retry_base_seconds)
    exponent = max(0, attempt_count - 1)
    return base * (2**exponent)


def job_session() -> Session:
    # A fresh session is required for each job execution thread.
    return SessionLocal()


def _claim_next_job(db: Session) -> SyncJob | None:
    now = utcnow()
    stmt = (
        select(SyncJob)
        .where(
            SyncJob.status == SyncJobStatus.QUEUED,
            SyncJob.next_run_at <= now,
        )
        .order_by(SyncJob.created_at.asc())
        .limit(1)
    )
    candidate = db.scalar(stmt)
    if not candidate:
        return None

    claim_stmt = (
        update(SyncJob)
        .where(SyncJob.id == candidate.id, SyncJob.status == SyncJobStatus.QUEUED)
        .values(
            status=SyncJobStatus.RUNNING,
            started_at=now,
            attempt_count=candidate.attempt_count + 1,
            last_error=None,
        )
    )
    claimed = db.execute(claim_stmt).rowcount == 1
    if not claimed:
        db.rollback()
        return None

    append_audit_event(
        db,
        event_type="integration.job.started",
        payload={"job_id": candidate.id, "job_type": candidate.job_type},
    )
    db.commit()
    return db.get(SyncJob, candidate.id)


def _complete_job_success(job_id: str, result: dict[str, Any]) -> None:
    with SessionLocal() as db:
        job = db.get(SyncJob, job_id)
        if not job:
            return
        job.status = SyncJobStatus.SUCCEEDED
        job.completed_at = utcnow()
        job.result = result
        append_audit_event(
            db,
            event_type="integration.job.succeeded",
            payload={"job_id": job.id, "job_type": job.job_type, "result": result},
        )
        db.commit()


def _complete_job_failure(job_id: str, error_message: str) -> None:
    with SessionLocal() as db:
        job = db.get(SyncJob, job_id)
        if not job:
            return

        job.last_error = error_message
        if job.attempt_count < job.max_attempts:
            delay_seconds = _retry_delay_seconds(job.attempt_count)
            job.status = SyncJobStatus.QUEUED
            job.next_run_at = utcnow() + timedelta(seconds=delay_seconds)
            append_audit_event(
                db,
                event_type="integration.job.retry_scheduled",
                payload={
                    "job_id": job.id,
                    "job_type": job.job_type,
                    "attempt_count": job.attempt_count,
                    "max_attempts": job.max_attempts,
                    "retry_in_seconds": delay_seconds,
                    "error": error_message,
                },
            )
        else:
            job.status = SyncJobStatus.FAILED
            job.completed_at = utcnow()
            append_audit_event(
                db,
                event_type="integration.job.failed",
                payload={
                    "job_id": job.id,
                    "job_type": job.job_type,
                    "attempt_count": job.attempt_count,
                    "max_attempts": job.max_attempts,
                    "error": error_message,
                },
            )
        db.commit()


def _execute_claimed_job(job: SyncJob) -> None:
    try:
        with job_session() as run_db:
            if job.job_type == JOB_TYPE_NETBOX_IMPORT:
                result = run_netbox_import(
                    db=run_db,
                    limit=int(job.payload.get("limit", settings.max_bulk_items)),
                    dry_run=bool(job.payload.get("dry_run", False)),
                    incremental=bool(job.payload.get("incremental", True)),
                )
            elif job.job_type == JOB_TYPE_BACKSTAGE_SYNC:
                result = run_backstage_sync(
                    db=run_db,
                    limit=int(job.payload.get("limit", settings.max_bulk_items)),
                    dry_run=bool(job.payload.get("dry_run", False)),
                )
            else:
                raise ValueError(f"Unsupported sync job type: {job.job_type}")

            if bool(job.payload.get("dry_run", False)):
                run_db.rollback()
            else:
                run_db.commit()
    except Exception as exc:
        logger.exception("Sync job execution failed", extra={"job_id": job.id, "job_type": job.job_type})
        _complete_job_failure(job.id, str(exc))
        return

    _complete_job_success(job.id, result)


def process_next_sync_job() -> bool:
    with SessionLocal() as db:
        job = _claim_next_job(db)
    if not job:
        return False
    _execute_claimed_job(job)
    return True


def _worker_loop() -> None:
    logger.info("Sync worker started")
    poll_interval = max(1, settings.sync_worker_poll_seconds)
    while not _worker_stop_event.is_set():
        processed = False
        try:
            processed = process_next_sync_job()
        except Exception:
            logger.exception("Sync worker loop error")
        if not processed:
            _worker_stop_event.wait(poll_interval)
    logger.info("Sync worker stopped")


def start_sync_worker() -> None:
    global _worker_thread
    with _worker_lock:
        if _worker_thread and _worker_thread.is_alive():
            return
        _worker_stop_event.clear()
        _worker_thread = threading.Thread(target=_worker_loop, name="sync-worker", daemon=True)
        _worker_thread.start()


def stop_sync_worker() -> None:
    global _worker_thread
    with _worker_lock:
        if not _worker_thread:
            return
        _worker_stop_event.set()
        _worker_thread.join(timeout=5)
        _worker_thread = None
