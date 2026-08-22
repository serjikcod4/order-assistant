from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Header, Request, Response, status

from order_assistant.api.container import AppContainer
from order_assistant.api.schemas import (
    OrderRequestResponse,
    TextOrderRequest,
    TextOrderRequestResponse,
)
from order_assistant.application.workflow import process_extracted_order
from order_assistant.domain import ExtractedOrder, OrderProcessingStatus


router = APIRouter(prefix="/order-requests", tags=["order requests"])


def _container(request: Request) -> AppContainer:
    return request.app.state.container


@router.post(
    "",
    response_model=OrderRequestResponse,
    summary="Process a structured order request",
    description=(
        "Accepts already structured data. This endpoint does not perform "
        "AI extraction from free-form customer text. It is temporarily "
        "unauthenticated for development."
    ),
)
def create_order_request(
    extracted: ExtractedOrder,
    request: Request,
    response: Response,
) -> OrderRequestResponse:
    container = _container(request)
    return _process(extracted, container, response)


@router.post(
    "/from-text",
    response_model=TextOrderRequestResponse,
    summary="Extract and process free-form order text with local Ollama",
    description="Development endpoint. Ollama only extracts fields; deterministic workflow selects inventory.",
)
def create_order_request_from_text(
    body: TextOrderRequest,
    request: Request,
    response: Response,
    request_id_header: Annotated[str | None, Header(alias="X-Request-ID")] = None,
) -> TextOrderRequestResponse:
    container = _container(request)
    try:
        request_id = UUID(request_id_header) if request_id_header else uuid4()
    except ValueError:
        request_id = uuid4()
    request.state.request_id = request_id
    response.headers["X-Request-ID"] = str(request_id)
    result = container.extraction_audit_service.process_text(body.text, request_id)
    if result.draft is not None:
        response.status_code = status.HTTP_201_CREATED
    return TextOrderRequestResponse(
        status=result.audit.processing_outcome.value,
        request_id=request_id,
        audit_id=result.audit.audit_id,
        guarded_result=result.extracted,
        grounding_issues=result.grounding_issues,
        processing=result.processing,
        draft_id=result.draft.draft_id if result.draft else None,
    )


def _process(
    extracted: ExtractedOrder,
    container: AppContainer,
    response: Response,
) -> OrderRequestResponse:
    processing = process_extracted_order(extracted, container.inventory)
    if processing.status != OrderProcessingStatus.DRAFT_READY:
        return OrderRequestResponse(processing=processing)

    draft = container.draft_service.create_draft(processing)
    response.status_code = status.HTTP_201_CREATED
    return OrderRequestResponse(processing=processing, draft_id=draft.draft_id)
