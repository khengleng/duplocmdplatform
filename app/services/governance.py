from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.time import utcnow
from app.models import CollisionStatus, GovernanceCollision
from app.services.audit import append_audit_event


def list_open_collisions(db: Session) -> list[GovernanceCollision]:
    stmt = select(GovernanceCollision).where(GovernanceCollision.status == CollisionStatus.OPEN)
    return list(db.scalars(stmt))


def resolve_collision(db: Session, collision_id: int, resolution_note: str) -> GovernanceCollision | None:
    collision = db.get(GovernanceCollision, collision_id)
    if not collision:
        return None

    collision.status = CollisionStatus.RESOLVED
    collision.resolution_note = resolution_note
    collision.resolved_at = utcnow()

    append_audit_event(
        db,
        "governance.collision.resolved",
        {
            "collision_id": collision.id,
            "scheme": collision.scheme,
            "value": collision.value,
            "resolution_note": resolution_note,
        },
        ci_id=collision.existing_ci_id,
    )

    db.flush()
    return collision
