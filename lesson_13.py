"""Lesson 13: timeout-safe submission and reconciliation demo."""

from order_assistant.application.submissions import ResilientOrderService
from order_assistant.application.drafts import DraftService
from order_assistant.domain import (
    CreatedOrder,
    DraftStatus,
    ERPPermanentError,
    ERPFailureMode,
    ERPTimeoutError,
    IdempotencyKeyConflictError,
    InvalidSubmissionStateError,
    OrderSubmission,
    OrderDraft,
    SubmissionNotFoundError,
    SubmissionStatus,
)
from order_assistant.infrastructure.erp import FakeERPClient, ResilientFakeERPClient
from order_assistant.infrastructure.repositories import (
    InMemoryDraftRepository,
    InMemorySubmissionRepository,
)


def main() -> None:
    from lesson_08 import inventory
    from lesson_10 import MockOrderExtractor
    from lesson_11 import process_customer_order
    from lesson_12 import DraftService, FakeERPClient, InMemoryDraftRepository

    response_data = {
        "model": "6204", "quantity": 500, "primary_brand": "SKF",
        "fallback_brands": ["FAG"], "max_unit_price": "250",
        "delivery_deadline": "2026-08-15T09:00:00",
        "allow_split_fulfillment": False, "requires_clarification": False,
        "clarification_questions": [],
    }
    result = process_customer_order(
        "Нужно 500 подшипников SKF 6204.",
        MockOrderExtractor(response_data),
        inventory,
    )
    draft_repository = InMemoryDraftRepository()
    draft_service = DraftService(draft_repository, FakeERPClient())
    draft = draft_service.create_draft(result)
    draft_service.approve_draft(draft.draft_id, "manager@example.com")
    erp_client = ResilientFakeERPClient(ERPFailureMode.TIMEOUT_AFTER_CREATION)
    service = ResilientOrderService(
        draft_repository,
        InMemorySubmissionRepository(),
        erp_client,
    )
    submission = service.submit_approved_draft(draft.draft_id, "demo-1")
    print(f"Статус после timeout: {submission.status.value}")
    print(f"Фактически создано заказов: {erp_client.actual_creation_count}")
    submission = service.reconcile_submission(submission.submission_id)
    print(f"Статус после reconciliation: {submission.status.value}")
    print(f"Фактически создано заказов: {erp_client.actual_creation_count}")


if __name__ == "__main__":
    main()
