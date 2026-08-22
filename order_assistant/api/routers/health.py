from fastapi import APIRouter, Request, Response, status

from order_assistant.api.container import AppContainer
from order_assistant.api.schemas import HealthResponse, ReadinessResponse


router = APIRouter(tags=["health"])


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Check API health",
)
def health_check() -> HealthResponse:
    return HealthResponse()


@router.get("/health/live", response_model=HealthResponse)
def liveness() -> HealthResponse:
    return HealthResponse()


@router.get("/health/ready", response_model=ReadinessResponse)
def readiness(request: Request, response: Response) -> ReadinessResponse:
    container: AppContainer = request.app.state.container
    if container.readiness_service is None:
        return ReadinessResponse(status="ready", details={"configuration": "ok"})
    ready, details = container.readiness_service.check()
    if not ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return ReadinessResponse(
        status="ready" if ready else "not_ready",
        details=details,
    )
