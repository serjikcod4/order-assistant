from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request

from order_assistant.api.container import AppContainer
from order_assistant.api.dependencies import get_current_actor
from order_assistant.api.schemas import (
    AUTH_ERROR_RESPONSES,
    ExtractionAuditDetail,
    ExtractionAuditSummary,
    ExtractionReviewRequest,
)
from order_assistant.application.authorization import require_permission
from order_assistant.domain import Actor, ExtractionReview, Permission


router = APIRouter(prefix="/extraction-audits", tags=["extraction audits"])


def _container(request: Request) -> AppContainer:
    return request.app.state.container


@router.get(
    "/summary",
    response_model=ExtractionAuditSummary,
    responses=AUTH_ERROR_RESPONSES,
)
def get_extraction_audit_summary(
    request: Request,
    actor: Annotated[Actor, Depends(get_current_actor)],
) -> ExtractionAuditSummary:
    require_permission(actor, Permission.READ_EXTRACTION_AUDIT)
    return ExtractionAuditSummary.model_validate(
        _container(request).extraction_audit_service.summary()
    )


@router.get(
    "/{audit_id}",
    response_model=ExtractionAuditDetail,
    responses=AUTH_ERROR_RESPONSES,
)
def get_extraction_audit(
    audit_id: UUID,
    request: Request,
    actor: Annotated[Actor, Depends(get_current_actor)],
) -> ExtractionAuditDetail:
    require_permission(actor, Permission.READ_EXTRACTION_AUDIT)
    audit, review = _container(request).extraction_audit_service.get_audit(audit_id)
    return ExtractionAuditDetail.from_domain(audit, review)


@router.post(
    "/{audit_id}/review",
    response_model=ExtractionReview,
    responses=AUTH_ERROR_RESPONSES,
)
def review_extraction(
    audit_id: UUID,
    body: ExtractionReviewRequest,
    request: Request,
    actor: Annotated[Actor, Depends(get_current_actor)],
) -> ExtractionReview:
    require_permission(actor, Permission.REVIEW_EXTRACTION)
    return _container(request).extraction_audit_service.review(
        audit_id=audit_id,
        reviewer_actor_id=actor.actor_id,
        decision=body.decision,
        corrected_order=body.corrected_order,
        correction_codes=body.correction_codes,
        comment=body.comment,
    )
