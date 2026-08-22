from datetime import datetime, timezone
from uuid import UUID, uuid4

from order_assistant.application.ports import DraftERPClient, DraftRepository, UnitOfWorkFactory
from order_assistant.domain import (
    DraftStatus,
    InvalidDraftResultError,
    InvalidStatusTransitionError,
    OrderDraft,
    OrderProcessingResult,
    OrderProcessingStatus,
)


class DraftService:
    def __init__(
        self,
        uow_factory: UnitOfWorkFactory | DraftRepository,
        erp_client: DraftERPClient,
    ) -> None:
        self.repository = None if callable(uow_factory) else uow_factory
        self._uow_factory = _as_factory(uow_factory)
        self.erp_client = erp_client

    def create_draft(self, processing_result: OrderProcessingResult) -> OrderDraft:
        if (
            processing_result.status != OrderProcessingStatus.DRAFT_READY
            or processing_result.selected_item is None
            or processing_result.requirements is None
            or not processing_result.requires_human_approval
        ):
            raise InvalidDraftResultError(
                "Only human-approved draft-ready results can create a draft."
            )
        draft = OrderDraft(
            draft_id=uuid4(),
            status=DraftStatus.DRAFT_READY,
            processing_result=processing_result,
            created_at=datetime.now(timezone.utc),
        )
        with self._uow_factory() as uow:
            uow.drafts.save(draft); uow.commit()
        return draft

    def approve_draft(self, draft_id: UUID, approved_by: str) -> OrderDraft:
        if not approved_by.strip():
            raise ValueError("approved_by cannot be empty.")
        with self._uow_factory() as uow:
            draft = uow.drafts.get(draft_id)
            if draft.status != DraftStatus.DRAFT_READY: raise InvalidStatusTransitionError("Only a draft-ready draft can be approved.")
            draft.status = DraftStatus.APPROVED; draft.approved_by = approved_by; draft.approved_at = datetime.now(timezone.utc)
            uow.drafts.save(draft); uow.commit()
        return draft

    def reject_draft(self, draft_id: UUID, rejected_by: str) -> OrderDraft:
        if not rejected_by.strip():
            raise ValueError("rejected_by cannot be empty.")
        with self._uow_factory() as uow:
            draft = uow.drafts.get(draft_id)
            if draft.status != DraftStatus.DRAFT_READY: raise InvalidStatusTransitionError("Only a draft-ready draft can be rejected.")
            draft.status = DraftStatus.REJECTED; draft.rejected_by = rejected_by; draft.rejected_at = datetime.now(timezone.utc)
            uow.drafts.save(draft); uow.commit()
        return draft

    def create_approved_order(self, draft_id: UUID, idempotency_key: str):
        if not idempotency_key.strip():
            raise ValueError("idempotency_key cannot be empty.")
        with self._uow_factory() as uow:
            draft = uow.drafts.get(draft_id)
        if draft.status == DraftStatus.ORDER_CREATED:
            if draft.created_order_id is None:
                raise InvalidStatusTransitionError("Created draft has no order ID.")
            return self.erp_client.get_order(draft.created_order_id)
        if draft.status != DraftStatus.APPROVED:
            raise InvalidStatusTransitionError(
                "Only an approved draft can create an order."
            )
        context_setter = getattr(self.erp_client, "set_call_context", None)
        if context_setter is not None:
            context_setter(uuid4(), draft)
        created_order = self.erp_client.create_order(draft, idempotency_key)
        draft.created_order_id = created_order.order_id
        draft.status = DraftStatus.ORDER_CREATED
        with self._uow_factory() as uow:
            current = uow.drafts.get(draft_id); current.created_order_id = created_order.order_id; current.status = DraftStatus.ORDER_CREATED; uow.drafts.save(current); uow.commit()
        return created_order


class _RepositoryUow:
    def __init__(self, drafts): self.drafts = drafts; self.submissions = None
    def __enter__(self): return self
    def __exit__(self, *args): return None
    def commit(self): return None
    def rollback(self): return None


def _as_factory(value):
    if callable(value): return value
    return lambda: _RepositoryUow(value)
