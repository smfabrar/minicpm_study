from fastapi import APIRouter
from .dependencies import ServiceContainer
from .schemas import ReviewInput
from ..domain.models import Review

router = APIRouter(prefix="/api/runs", tags=["runs"])


@router.get("/{run_id}")
def get_run(run_id: str, container: ServiceContainer):
    return container.runs.get(run_id)


@router.get("/{run_id}/telemetry")
def telemetry(run_id: str, container: ServiceContainer):
    return container.runs.telemetry(run_id)


@router.put("/{run_id}/review")
def review(run_id: str, body: ReviewInput, container: ServiceContainer):
    return container.runs.review(run_id, Review(**body.model_dump()))


@router.post("/{run_id}/transcribe", status_code=202)
def transcribe(run_id: str, container: ServiceContainer):
    return container.preparation.transcribe(run_id)


@router.post("/{run_id}/resume", status_code=202)
def resume(run_id: str, container: ServiceContainer):
    return container.runs.resume(run_id)
