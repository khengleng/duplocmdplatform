from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import require_mutation_rate_limit, require_service_auth
from app.models import CollisionStatus
from app.schemas import CollisionReopenRequest, CollisionResolveRequest, CollisionResolveResponse, CollisionResponse
from app.services.governance import list_collisions, reopen_collision, resolve_collision

router = APIRouter(prefix="/governance", tags=["governance"], dependencies=[Depends(require_service_auth)])


@router.get("/collisions", response_model=list[CollisionResponse])
def get_open_collisions(
    status: str = Query(default="open"),
    db: Session = Depends(get_db),
) -> list[CollisionResponse]:
    normalized_status = status.strip().lower()
    selected_status: CollisionStatus | None
    if normalized_status == "open":
        selected_status = CollisionStatus.OPEN
    elif normalized_status == "resolved":
        selected_status = CollisionStatus.RESOLVED
    elif normalized_status == "all":
        selected_status = None
    else:
        raise HTTPException(status_code=400, detail="Invalid collision status filter")

    collisions = list_collisions(db, status=selected_status)
    return [
        CollisionResponse(
            id=collision.id,
            scheme=collision.scheme,
            value=collision.value,
            existing_ci_id=collision.existing_ci_id,
            incoming_ci_id=collision.incoming_ci_id,
            status=collision.status,
            resolution_note=collision.resolution_note,
            resolved_at=collision.resolved_at,
            created_at=collision.created_at,
        )
        for collision in collisions
    ]


@router.post("/collisions/{collision_id}/resolve", response_model=CollisionResolveResponse)
def resolve_governance_collision(
    collision_id: int,
    request: CollisionResolveRequest,
    _rate_limit: None = Depends(require_mutation_rate_limit),
    db: Session = Depends(get_db),
) -> CollisionResolveResponse:
    collision = resolve_collision(db, collision_id=collision_id, resolution_note=request.resolution_note)
    if not collision:
        raise HTTPException(status_code=404, detail="Collision not found")

    db.commit()
    return CollisionResolveResponse(
        collision=CollisionResponse(
            id=collision.id,
            scheme=collision.scheme,
            value=collision.value,
            existing_ci_id=collision.existing_ci_id,
            incoming_ci_id=collision.incoming_ci_id,
            status=collision.status,
            resolution_note=collision.resolution_note,
            resolved_at=collision.resolved_at,
            created_at=collision.created_at,
        )
    )


@router.post("/collisions/{collision_id}/reopen", response_model=CollisionResolveResponse)
def reopen_governance_collision(
    collision_id: int,
    request: CollisionReopenRequest,
    _rate_limit: None = Depends(require_mutation_rate_limit),
    db: Session = Depends(get_db),
) -> CollisionResolveResponse:
    collision = reopen_collision(db, collision_id=collision_id, reopen_note=request.reopen_note)
    if not collision:
        raise HTTPException(status_code=404, detail="Collision not found")

    db.commit()
    return CollisionResolveResponse(
        collision=CollisionResponse(
            id=collision.id,
            scheme=collision.scheme,
            value=collision.value,
            existing_ci_id=collision.existing_ci_id,
            incoming_ci_id=collision.incoming_ci_id,
            status=collision.status,
            resolution_note=collision.resolution_note,
            resolved_at=collision.resolved_at,
            created_at=collision.created_at,
        )
    )
