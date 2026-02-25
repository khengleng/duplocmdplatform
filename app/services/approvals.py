from sqlalchemy import update
from sqlalchemy.orm import Session

from app.core.time import utcnow
from app.models import ApprovalStatus, ChangeApproval
from app.services.audit import append_audit_event


def expire_pending_approvals(db: Session) -> int:
    now = utcnow()
    expire_stmt = (
        update(ChangeApproval)
        .where(
            ChangeApproval.status == ApprovalStatus.PENDING,
            ChangeApproval.expires_at <= now,
        )
        .values(
            status=ApprovalStatus.REJECTED,
            decided_by="system:approval-cleaner",
            decision_note="expired",
            decided_at=now,
            updated_at=now,
        )
    )
    expired_count = db.execute(expire_stmt).rowcount or 0
    if expired_count > 0:
        append_audit_event(
            db,
            event_type="approval.expired",
            payload={"expired_count": expired_count, "at": now.isoformat()},
        )
    return expired_count
