from typing import Annotated

from fastapi import APIRouter, Depends, Request

from order_assistant.api.container import AppContainer
from order_assistant.api.dependencies import get_current_actor
from order_assistant.api.schemas import AUTH_ERROR_RESPONSES, LLMRuntimeSummary
from order_assistant.application.authorization import require_permission
from order_assistant.domain import Actor, Permission


router = APIRouter(prefix="/extraction-runtime", tags=["extraction runtime"])


@router.get(
    "/summary",
    response_model=LLMRuntimeSummary,
    responses=AUTH_ERROR_RESPONSES,
)
def runtime_summary(
    request: Request,
    actor: Annotated[Actor, Depends(get_current_actor)],
) -> LLMRuntimeSummary:
    require_permission(actor, Permission.READ_EXTRACTION_AUDIT)
    container: AppContainer = request.app.state.container
    return LLMRuntimeSummary.model_validate(
        container.extraction_audit_service.runtime_summary()
    )
