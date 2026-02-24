from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import require_mutation_rate_limit, require_service_auth
from app.schemas import LifecycleRunResponse
from app.services.lifecycle import run_lifecycle

router = APIRouter(
    prefix="/lifecycle",
    tags=["lifecycle"],
    dependencies=[Depends(require_service_auth), Depends(require_mutation_rate_limit)],
)


@router.post("/run", response_model=LifecycleRunResponse)
def trigger_lifecycle_run(db: Session = Depends(get_db)) -> LifecycleRunResponse:
    transitioned = run_lifecycle(db)
    db.commit()
    return LifecycleRunResponse(transitioned=transitioned)
