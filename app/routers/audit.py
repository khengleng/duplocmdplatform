import json

from fastapi import APIRouter, Depends, Query
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.services.audit import list_audit_events

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("/export", response_class=PlainTextResponse)
def export_audit_events(
    limit: int = Query(default=1000, ge=1, le=20000),
    db: Session = Depends(get_db),
) -> str:
    events = list_audit_events(db, limit=limit)
    lines = []
    for event in events:
        lines.append(
            json.dumps(
                {
                    "id": event.id,
                    "ci_id": event.ci_id,
                    "event_type": event.event_type,
                    "payload": event.payload,
                    "created_at": event.created_at.isoformat(),
                }
            )
        )
    return "\n".join(lines)
