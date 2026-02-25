import logging
import threading
import time
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from typing import Any

import httpx
from sqlalchemy import and_, select, update
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.core.telemetry import record_event
from app.core.time import utcnow
from app.models import SyncJob, SyncJobStatus, SyncState
from app.services.approvals import expire_pending_approvals
from app.services.audit import append_audit_event
from app.services.integrations import run_backstage_sync, run_netbox_import

logger = logging.getLogger(__name__)
settings = get_settings()

JOB_TYPE_NETBOX_IMPORT = "netbox.import"
JOB_TYPE_BACKSTAGE_SYNC = "backstage.sync"
SCHEDULE_NETBOX_IMPORT = "netbox-import"
SCHEDULE_BACKSTAGE_SYNC = "backstage-sync"

_worker_lock = threading.Lock()
_worker_thread: threading.Thread | None = None
_scheduler_thread: threading.Thread | None = None
_worker_stop_event = threading.Event()
_last_approval_cleanup_at: float = 0.0


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


def _schedule_next_run_key(schedule_name: str) -> str:
    return f"sync.schedule.{schedule_name}.next_run_at"


def _parse_iso_datetime(value: str | None) -> datetime | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    if normalized.endswith("Z"):
        normalized = f"{normalized[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is not None:
            return parsed.astimezone(timezone.utc).replace(tzinfo=None)
        return parsed
    except ValueError:
        return None


def _read_sync_state(db: Session, key: str) -> str | None:
    state = db.get(SyncState, key)
    return state.value if state else None


def _write_sync_state(db: Session, key: str, value: str) -> None:
    state = db.get(SyncState, key)
    if state is None:
        db.add(SyncState(key=key, value=value))
        return
    state.value = value


def _schedule_definitions() -> dict[str, dict[str, Any]]:
    return {
        SCHEDULE_NETBOX_IMPORT: {
            "job_type": JOB_TYPE_NETBOX_IMPORT,
            "enabled": settings.sync_schedule_netbox_import_enabled,
            "interval_seconds": max(30, settings.sync_schedule_netbox_import_interval_seconds),
            "payload": {
                "limit": settings.sync_schedule_netbox_import_limit,
                "dry_run": False,
                "incremental": True,
            },
        },
        SCHEDULE_BACKSTAGE_SYNC: {
            "job_type": JOB_TYPE_BACKSTAGE_SYNC,
            "enabled": settings.sync_schedule_backstage_sync_enabled,
            "interval_seconds": max(30, settings.sync_schedule_backstage_sync_interval_seconds),
            "payload": {
                "limit": settings.sync_schedule_backstage_sync_limit,
                "dry_run": False,
            },
        },
    }


def _is_schedule_ready(schedule_name: str) -> tuple[bool, str | None]:
    if schedule_name == SCHEDULE_NETBOX_IMPORT:
        if not settings.netbox_api_url.strip():
            return False, "netbox_api_url_missing"
        if not settings.netbox_api_token.strip():
            return False, "netbox_api_token_missing"
        return True, None

    if schedule_name == SCHEDULE_BACKSTAGE_SYNC:
        if not settings.backstage_sync_enabled:
            return False, "backstage_sync_disabled"
        if not settings.backstage_sync_url.strip():
            return False, "backstage_sync_url_missing"
        if not (settings.backstage_sync_token.strip() or settings.backstage_sync_secret.strip()):
            return False, "backstage_auth_missing"
        return True, None

    return False, "unknown_schedule"


def list_sync_schedules(db: Session) -> list[dict[str, Any]]:
    schedules: list[dict[str, Any]] = []
    definitions = _schedule_definitions()
    for schedule_name, definition in definitions.items():
        next_run = _read_sync_state(db, _schedule_next_run_key(schedule_name))
        ready, reason = _is_schedule_ready(schedule_name)
        inflight_stmt = select(SyncJob.id).where(
            and_(
                SyncJob.job_type == definition["job_type"],
                SyncJob.requested_by == "scheduler",
                SyncJob.status.in_([SyncJobStatus.QUEUED, SyncJobStatus.RUNNING]),
            )
        )
        schedules.append(
            {
                "name": schedule_name,
                "job_type": definition["job_type"],
                "enabled": bool(definition["enabled"]),
                "interval_seconds": int(definition["interval_seconds"]),
                "payload": definition["payload"],
                "next_run_at": next_run,
                "has_inflight_job": db.scalar(inflight_stmt) is not None,
                "ready": ready,
                "not_ready_reason": reason,
            }
        )
    return schedules


def enqueue_schedule_job_now(
    db: Session,
    schedule_name: str,
    requested_by: str | None = None,
) -> SyncJob:
    definition = _schedule_definitions().get(schedule_name)
    if not definition:
        raise ValueError("unknown_schedule")
    payload = dict(definition["payload"])
    payload["scheduled"] = True
    payload["schedule_name"] = schedule_name
    return enqueue_sync_job(
        db,
        job_type=definition["job_type"],
        payload=payload,
        requested_by=requested_by or "scheduler-manual",
    )


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
    failed_terminally = False
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
            failed_terminally = True
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
    if failed_terminally:
        record_event("sync.job_failed")


def _safe_job_error(exc: Exception) -> str:
    if isinstance(exc, ValueError):
        candidate = str(exc).strip().lower()
        if candidate and len(candidate) <= 80 and all(ch.islower() or ch.isdigit() or ch in {"_", "-", "."} for ch in candidate):
            return candidate
    if isinstance(exc, httpx.HTTPStatusError):
        return "upstream_http_error"
    if isinstance(exc, httpx.HTTPError):
        return "upstream_request_error"
    return "job_execution_failed"


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
        _complete_job_failure(job.id, _safe_job_error(exc))
        return

    _complete_job_success(job.id, result)


def process_next_sync_job() -> bool:
    with SessionLocal() as db:
        job = _claim_next_job(db)
    if not job:
        return False
    _execute_claimed_job(job)
    return True


def _has_inflight_scheduler_job(db: Session, job_type: str) -> bool:
    stmt = select(SyncJob.id).where(
        and_(
            SyncJob.job_type == job_type,
            SyncJob.requested_by == "scheduler",
            SyncJob.status.in_([SyncJobStatus.QUEUED, SyncJobStatus.RUNNING]),
        )
    )
    return db.scalar(stmt) is not None


def _evaluate_schedule(db: Session, schedule_name: str, definition: dict[str, Any], now: datetime) -> bool:
    if not bool(definition["enabled"]):
        return False

    state_key = _schedule_next_run_key(schedule_name)
    next_run = _parse_iso_datetime(_read_sync_state(db, state_key))
    if next_run is not None and next_run > now:
        return False

    ready, not_ready_reason = _is_schedule_ready(schedule_name)
    if not ready:
        next_run_at = now + timedelta(seconds=int(definition["interval_seconds"]))
        _write_sync_state(db, state_key, next_run_at.isoformat())
        append_audit_event(
            db,
            event_type="integration.schedule.skipped",
            payload={"schedule": schedule_name, "reason": not_ready_reason},
        )
        return False

    enqueued = False
    if not _has_inflight_scheduler_job(db, definition["job_type"]):
        payload = dict(definition["payload"])
        payload["scheduled"] = True
        payload["schedule_name"] = schedule_name
        enqueue_sync_job(
            db,
            job_type=definition["job_type"],
            payload=payload,
            requested_by="scheduler",
        )
        append_audit_event(
            db,
            event_type="integration.schedule.triggered",
            payload={"schedule": schedule_name, "job_type": definition["job_type"]},
        )
        enqueued = True

    next_run_at = now + timedelta(seconds=int(definition["interval_seconds"]))
    _write_sync_state(db, state_key, next_run_at.isoformat())
    return enqueued


def process_sync_schedules() -> bool:
    if not settings.sync_scheduler_enabled:
        return False

    triggered = False
    now = utcnow()
    definitions = _schedule_definitions()
    with SessionLocal() as db:
        for schedule_name, definition in definitions.items():
            if _evaluate_schedule(db, schedule_name, definition, now):
                triggered = True
        db.commit()
    return triggered


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


def _scheduler_loop() -> None:
    logger.info("Sync scheduler started")
    poll_interval = max(1, settings.sync_worker_poll_seconds)
    cleanup_interval = max(15, settings.approval_cleanup_interval_seconds)
    global _last_approval_cleanup_at
    while not _worker_stop_event.is_set():
        try:
            now_monotonic = time.monotonic()
            if now_monotonic - _last_approval_cleanup_at >= cleanup_interval:
                with SessionLocal() as db:
                    expired_count = expire_pending_approvals(db)
                    if expired_count > 0:
                        db.commit()
                    else:
                        db.rollback()
                _last_approval_cleanup_at = now_monotonic
            process_sync_schedules()
        except Exception:
            logger.exception("Sync scheduler loop error")
        _worker_stop_event.wait(poll_interval)
    logger.info("Sync scheduler stopped")


def start_sync_worker() -> None:
    global _worker_thread, _scheduler_thread
    with _worker_lock:
        if _worker_thread and _worker_thread.is_alive():
            return
        _worker_stop_event.clear()
        _worker_thread = threading.Thread(target=_worker_loop, name="sync-worker", daemon=True)
        _scheduler_thread = threading.Thread(target=_scheduler_loop, name="sync-scheduler", daemon=True)
        _worker_thread.start()
        _scheduler_thread.start()


def stop_sync_worker() -> None:
    global _worker_thread, _scheduler_thread
    with _worker_lock:
        if not _worker_thread:
            return
        _worker_stop_event.set()
        _worker_thread.join(timeout=5)
        if _scheduler_thread:
            _scheduler_thread.join(timeout=5)
        _worker_thread = None
        _scheduler_thread = None
