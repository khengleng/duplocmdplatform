from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas import LifecycleRunResponse
from app.services.lifecycle import run_lifecycle

router = APIRouter(prefix="/lifecycle", tags=["lifecycle"])


@router.post("/run", response_model=LifecycleRunResponse)
def trigger_lifecycle_run(db: Session = Depends(get_db)) -> LifecycleRunResponse:
    transitioned = run_lifecycle(db)
    db.commit()
    return LifecycleRunResponse(transitioned=transitioned)
