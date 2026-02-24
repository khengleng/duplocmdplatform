from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas import CollisionResolveRequest, CollisionResolveResponse, CollisionResponse
from app.services.governance import list_open_collisions, resolve_collision

router = APIRouter(prefix="/governance", tags=["governance"])


@router.get("/collisions", response_model=list[CollisionResponse])
def get_open_collisions(db: Session = Depends(get_db)) -> list[CollisionResponse]:
    collisions = list_open_collisions(db)
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
