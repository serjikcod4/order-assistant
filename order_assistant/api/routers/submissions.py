from uuid import UUID

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status

from order_assistant.api.container import AppContainer
from order_assistant.api.dependencies import get_current_actor
from order_assistant.api.schemas import AUTH_ERROR_RESPONSES, SubmissionRequest
from order_assistant.application.authorization import require_permission
from order_assistant.application.submissions import idempotency_key_for_draft
from order_assistant.domain import (
    Actor,
    ERPPermanentError,
    OrderSubmission,
    Permission,
    SubmissionStatus,
)


router = APIRouter(tags=["submissions"])


def _container(request: Request) -> AppContainer:
    return request.app.state.container


def _submission_response_status(
    submission: OrderSubmission,
    response: Response,
) -> OrderSubmission:
    if submission.status == SubmissionStatus.UNKNOWN:
        response.status_code = status.HTTP_202_ACCEPTED
    elif submission.status == SubmissionStatus.PERMANENTLY_FAILED:
        raise ERPPermanentError(submission.last_error or "ERP permanently failed.")
    else:
        response.status_code = status.HTTP_201_CREATED
    return submission


@router.post(
    "/drafts/{draft_id}/submit",
    response_model=OrderSubmission,
    summary="Submit an approved draft through the configured ERP adapter",
    responses=AUTH_ERROR_RESPONSES,
)
def submit_draft(
    draft_id: UUID,
    submission_request: SubmissionRequest,
    request: Request,
    response: Response,
    actor: Annotated[Actor, Depends(get_current_actor)],
) -> OrderSubmission:
    del submission_request
    require_permission(actor, Permission.SUBMIT_ORDER)
    submission = _container(request).submission_service.submit_approved_draft(
        draft_id,
        idempotency_key_for_draft(draft_id),
    )
    return _submission_response_status(submission, response)


@router.post(
    "/submissions/{submission_id}/retry",
    response_model=OrderSubmission,
    summary="Retry an unknown submission with its saved idempotency key",
    responses=AUTH_ERROR_RESPONSES,
)
def retry_submission(
    submission_id: UUID,
    request: Request,
    response: Response,
    actor: Annotated[Actor, Depends(get_current_actor)],
) -> OrderSubmission:
    require_permission(actor, Permission.RETRY_SUBMISSION)
    submission = _container(request).submission_service.retry_submission(submission_id)
    return _submission_response_status(submission, response)


@router.post(
    "/submissions/{submission_id}/reconcile",
    response_model=OrderSubmission,
    summary="Find a potentially created ERP order without creating a new one",
    responses=AUTH_ERROR_RESPONSES,
)
def reconcile_submission(
    submission_id: UUID,
    request: Request,
    response: Response,
    actor: Annotated[Actor, Depends(get_current_actor)],
) -> OrderSubmission:
    require_permission(actor, Permission.RECONCILE_SUBMISSION)
    submission = _container(request).submission_service.reconcile_submission(
        submission_id
    )
    if submission.status == SubmissionStatus.UNKNOWN:
        response.status_code = status.HTTP_202_ACCEPTED
    else:
        response.status_code = status.HTTP_200_OK
    return submission


@router.get(
    "/submissions/{submission_id}",
    response_model=OrderSubmission,
    summary="Get a saved ERP submission",
    responses=AUTH_ERROR_RESPONSES,
)
def get_submission(
    submission_id: UUID,
    request: Request,
    actor: Annotated[Actor, Depends(get_current_actor)],
) -> OrderSubmission:
    require_permission(actor, Permission.READ_SUBMISSION)
    return _container(request).submission_repository.get(submission_id)
