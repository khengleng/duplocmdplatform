from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AuditEvent


def append_audit_event(db: Session, event_type: str, payload: dict, ci_id: str | None = None) -> AuditEvent:
    event = AuditEvent(ci_id=ci_id, event_type=event_type, payload=payload)
    db.add(event)
    db.flush()
    return event


def list_ci_audit_events(db: Session, ci_id: str) -> list[AuditEvent]:
    stmt = select(AuditEvent).where(AuditEvent.ci_id == ci_id).order_by(AuditEvent.created_at.desc())
    return list(db.scalars(stmt))


def list_audit_events(db: Session, limit: int = 1000) -> list[AuditEvent]:
    stmt = select(AuditEvent).order_by(AuditEvent.created_at.desc()).limit(limit)
    return list(db.scalars(stmt))
