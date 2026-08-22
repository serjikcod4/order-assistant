"""Lesson 12: human approval and idempotent fake ERP demo."""

from order_assistant.application.drafts import DraftService
from order_assistant.domain import (
    CreatedOrder,
    DraftNotFoundError,
    DraftStatus,
    InvalidDraftResultError,
    InvalidStatusTransitionError,
    OrderDraft,
    OrderProcessingResult,
    OrderProcessingStatus,
)
from order_assistant.infrastructure.erp import FakeERPClient
from order_assistant.infrastructure.extractors import MockOrderExtractor
from order_assistant.infrastructure.repositories import InMemoryDraftRepository


def main() -> None:
    from lesson_08 import inventory
    from order_assistant.application.workflow import process_customer_order

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
    erp_client = FakeERPClient()
    service = DraftService(InMemoryDraftRepository(), erp_client)
    draft = service.create_draft(result)
    print(f"Статус черновика: {draft.status.value}")
    draft = service.approve_draft(draft.draft_id, "manager@example.com")
    print(f"Статус черновика: {draft.status.value}")
    first_order = service.create_approved_order(draft.draft_id, "demo-order-1")
    repeated_order = service.create_approved_order(draft.draft_id, "demo-order-1")
    print(f"ID заказа совпадают: {first_order.order_id == repeated_order.order_id}")
    print(f"Количество созданий: {erp_client.create_call_count}")


if __name__ == "__main__":
    main()
