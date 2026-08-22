import subprocess
import sys
from uuid import uuid4

import pytest

from lesson_08 import inventory
from lesson_10 import MockOrderExtractor
from lesson_11 import process_customer_order
from lesson_12 import (
    DraftNotFoundError,
    DraftService,
    DraftStatus,
    FakeERPClient,
    InMemoryDraftRepository,
    InvalidDraftResultError,
    InvalidStatusTransitionError,
)


FULL_RESPONSE = {
    "model": "6204",
    "quantity": 500,
    "primary_brand": "SKF",
    "fallback_brands": ["FAG"],
    "max_unit_price": "250",
    "delivery_deadline": "2026-08-15T09:00:00",
    "allow_split_fulfillment": False,
    "requires_clarification": False,
    "clarification_questions": [],
}


def create_processing_result(response_data: dict[str, object] = FULL_RESPONSE):
    return process_customer_order(
        "Нужно 500 подшипников SKF 6204.",
        MockOrderExtractor(response_data),
        inventory,
    )


def create_service_and_draft():
    erp_client = FakeERPClient()
    service = DraftService(InMemoryDraftRepository(), erp_client)
    draft = service.create_draft(create_processing_result())
    return service, erp_client, draft


def create_approved_draft():
    service, erp_client, draft = create_service_and_draft()
    return service, erp_client, service.approve_draft(draft.draft_id, "manager@example.com")


def test_draft_is_created_only_from_draft_ready_result() -> None:
    service = DraftService(InMemoryDraftRepository(), FakeERPClient())
    incomplete_result = create_processing_result({**FULL_RESPONSE, "quantity": None})

    with pytest.raises(InvalidDraftResultError):
        service.create_draft(incomplete_result)


def test_new_draft_has_draft_ready_status() -> None:
    _, _, draft = create_service_and_draft()

    assert draft.status == DraftStatus.DRAFT_READY
    assert draft.created_at.tzinfo is not None


def test_order_cannot_be_created_before_approval() -> None:
    service, _, draft = create_service_and_draft()

    with pytest.raises(InvalidStatusTransitionError):
        service.create_approved_order(draft.draft_id, "order-1")


def test_approve_changes_status_to_approved() -> None:
    service, _, draft = create_service_and_draft()

    approved_draft = service.approve_draft(draft.draft_id, "manager@example.com")

    assert approved_draft.status == DraftStatus.APPROVED


def test_approval_details_are_saved() -> None:
    service, _, draft = create_service_and_draft()

    approved_draft = service.approve_draft(draft.draft_id, "manager@example.com")

    assert approved_draft.approved_by == "manager@example.com"
    assert approved_draft.approved_at is not None
    assert approved_draft.approved_at.tzinfo is not None


def test_reject_changes_status_to_rejected() -> None:
    service, _, draft = create_service_and_draft()

    rejected_draft = service.reject_draft(draft.draft_id, "manager@example.com")

    assert rejected_draft.status == DraftStatus.REJECTED


def test_rejected_draft_cannot_be_approved() -> None:
    service, _, draft = create_service_and_draft()
    service.reject_draft(draft.draft_id, "manager@example.com")

    with pytest.raises(InvalidStatusTransitionError):
        service.approve_draft(draft.draft_id, "another@example.com")


def test_rejected_draft_cannot_create_order() -> None:
    service, _, draft = create_service_and_draft()
    service.reject_draft(draft.draft_id, "manager@example.com")

    with pytest.raises(InvalidStatusTransitionError):
        service.create_approved_order(draft.draft_id, "order-1")


def test_approved_draft_creates_one_order() -> None:
    service, erp_client, draft = create_approved_draft()

    service.create_approved_order(draft.draft_id, "order-1")

    assert erp_client.create_call_count == 1


def test_creating_order_changes_draft_status() -> None:
    service, _, draft = create_approved_draft()

    service.create_approved_order(draft.draft_id, "order-1")

    assert service.repository.get(draft.draft_id).status == DraftStatus.ORDER_CREATED


def test_same_idempotency_key_returns_same_order_id() -> None:
    service, _, draft = create_approved_draft()

    first_order = service.create_approved_order(draft.draft_id, "order-1")
    repeated_order = service.create_approved_order(draft.draft_id, "order-1")

    assert repeated_order.order_id == first_order.order_id


def test_repeated_creation_does_not_increase_call_count() -> None:
    service, erp_client, draft = create_approved_draft()

    service.create_approved_order(draft.draft_id, "order-1")
    service.create_approved_order(draft.draft_id, "order-1")

    assert erp_client.create_call_count == 1


def test_order_created_draft_ignores_a_different_idempotency_key() -> None:
    service, erp_client, draft = create_approved_draft()

    first_order = service.create_approved_order(draft.draft_id, "order-1")
    repeated_order = service.create_approved_order(draft.draft_id, "order-2")

    assert repeated_order.order_id == first_order.order_id
    assert erp_client.create_call_count == 1


def test_missing_draft_raises_not_found_error() -> None:
    service = DraftService(InMemoryDraftRepository(), FakeERPClient())

    with pytest.raises(DraftNotFoundError):
        service.approve_draft(uuid4(), "manager@example.com")


def test_empty_approver_rejector_and_idempotency_key_are_rejected() -> None:
    service, _, draft = create_service_and_draft()

    with pytest.raises(ValueError):
        service.approve_draft(draft.draft_id, "")
    with pytest.raises(ValueError):
        service.reject_draft(draft.draft_id, "")

    approved_draft = service.approve_draft(draft.draft_id, "manager@example.com")
    with pytest.raises(ValueError):
        service.create_approved_order(approved_draft.draft_id, "")


def test_importing_lesson_12_produces_no_output() -> None:
    result = subprocess.run(
        [sys.executable, "-c", "import lesson_12"],
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.stdout == ""
    assert result.stderr == ""
