from uuid import UUID

from typing import Annotated

from fastapi import APIRouter, Depends, Request

from order_assistant.api.container import AppContainer
from order_assistant.api.dependencies import get_current_actor
from order_assistant.api.schemas import AUTH_ERROR_RESPONSES
from order_assistant.application.authorization import require_permission
from order_assistant.domain import Actor, OrderDraft, Permission


router = APIRouter(prefix="/drafts", tags=["drafts"])


def _container(request: Request) -> AppContainer:
    return request.app.state.container


@router.get(
    "/{draft_id}",
    response_model=OrderDraft,
    summary="Get an order draft",
    responses=AUTH_ERROR_RESPONSES,
)
def get_draft(
    draft_id: UUID,
    request: Request,
    actor: Annotated[Actor, Depends(get_current_actor)],
) -> OrderDraft:
    require_permission(actor, Permission.READ_DRAFT)
    return _container(request).draft_repository.get(draft_id)


@router.post(
    "/{draft_id}/approve",
    response_model=OrderDraft,
    summary="Approve a draft as a human reviewer",
    responses=AUTH_ERROR_RESPONSES,
)
def approve_draft(
    draft_id: UUID,
    request: Request,
    actor: Annotated[Actor, Depends(get_current_actor)],
) -> OrderDraft:
    require_permission(actor, Permission.APPROVE_DRAFT)
    return _container(request).draft_service.approve_draft(
        draft_id,
        actor.actor_id,
    )


@router.post(
    "/{draft_id}/reject",
    response_model=OrderDraft,
    summary="Reject a draft as a human reviewer",
    responses=AUTH_ERROR_RESPONSES,
)
def reject_draft(
    draft_id: UUID,
    request: Request,
    actor: Annotated[Actor, Depends(get_current_actor)],
) -> OrderDraft:
    require_permission(actor, Permission.REJECT_DRAFT)
    return _container(request).draft_service.reject_draft(
        draft_id,
        actor.actor_id,
    )
