import subprocess
import sys

import order_assistant
from order_assistant.application.drafts import DraftService
from order_assistant.application.submissions import ResilientOrderService
from order_assistant.application.workflow import process_customer_order
from order_assistant.domain import DraftStatus, ERPFailureMode, SubmissionStatus
from order_assistant.infrastructure.erp import FakeERPClient, ResilientFakeERPClient
from order_assistant.infrastructure.extractors import MockOrderExtractor
from order_assistant.infrastructure.repositories import (
    InMemoryDraftRepository,
    InMemorySubmissionRepository,
)


RESPONSE_DATA = {
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


INVENTORY = [
    order_assistant.InventoryItem.model_validate(
        {
            "sku": "SKU-23",
            "brand": "FAG",
            "model": "6204",
            "stock": 600,
            "unit_price": "240",
            "delivery_available_at": "2026-08-15T08:30:00",
        }
    )
]


def create_approved_draft():
    result = process_customer_order(
        "Нужно 500 подшипников SKF 6204.",
        MockOrderExtractor(RESPONSE_DATA),
        INVENTORY,
    )
    draft_repository = InMemoryDraftRepository()
    draft_service = DraftService(draft_repository, FakeERPClient())
    draft = draft_service.create_draft(result)
    return draft_repository, draft_service.approve_draft(
        draft.draft_id,
        "manager@example.com",
    )


def test_package_imports_and_exposes_domain_models() -> None:
    assert order_assistant.Brand.SKF.value == "SKF"
    assert order_assistant.OrderRequirements
    assert order_assistant.InventoryItem
    assert order_assistant.ExtractedOrder
    assert order_assistant.OrderDraft
    assert order_assistant.OrderSubmission


def test_application_workflow_works_with_infrastructure_adapters() -> None:
    result = process_customer_order(
        "Нужно 500 подшипников SKF 6204.",
        MockOrderExtractor(RESPONSE_DATA),
        INVENTORY,
    )

    assert result.selected_item is not None
    assert result.selected_item.sku == "SKU-23"


def test_package_modules_import_without_output_or_circular_imports() -> None:
    modules = [
        "order_assistant",
        "order_assistant.domain",
        "order_assistant.domain.enums",
        "order_assistant.domain.models",
        "order_assistant.domain.exceptions",
        "order_assistant.application",
        "order_assistant.application.ports",
        "order_assistant.application.clarifications",
        "order_assistant.application.extraction",
        "order_assistant.application.grounding",
        "order_assistant.evaluation.datasets",
        "order_assistant.evaluation.release",
        "order_assistant.application.matching",
        "order_assistant.application.workflow",
        "order_assistant.application.drafts",
        "order_assistant.application.submissions",
        "order_assistant.infrastructure",
        "order_assistant.infrastructure.extractors",
        "order_assistant.infrastructure.repositories",
        "order_assistant.infrastructure.erp",
        "lesson_08",
        "lesson_10",
        "lesson_11",
        "lesson_12",
        "lesson_13",
        "lesson_14",
        "lesson_15",
        "lesson_16",
        "lesson_17",
    ]
    command = "import importlib; " + "; ".join(
        f"importlib.import_module('{module}')" for module in modules
    )
    result = subprocess.run(
        [sys.executable, "-c", command],
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.stdout == ""
    assert result.stderr == ""


def test_end_to_end_flow_ends_with_order_created() -> None:
    draft_repository, draft = create_approved_draft()
    erp_client = ResilientFakeERPClient()
    service = ResilientOrderService(
        draft_repository,
        InMemorySubmissionRepository(),
        erp_client,
    )

    submission = service.submit_approved_draft(draft.draft_id, "architecture-e2e")

    assert submission.status == SubmissionStatus.SUCCEEDED
    assert draft_repository.get(draft.draft_id).status == DraftStatus.ORDER_CREATED
    assert erp_client.actual_creation_count == 1


def test_timeout_after_creation_reconciles_without_duplicate() -> None:
    draft_repository, draft = create_approved_draft()
    erp_client = ResilientFakeERPClient(ERPFailureMode.TIMEOUT_AFTER_CREATION)
    service = ResilientOrderService(
        draft_repository,
        InMemorySubmissionRepository(),
        erp_client,
    )
    submission = service.submit_approved_draft(draft.draft_id, "architecture-timeout")

    reconciled_submission = service.reconcile_submission(submission.submission_id)

    assert submission.status == SubmissionStatus.SUCCEEDED
    assert reconciled_submission.status == SubmissionStatus.SUCCEEDED
    assert erp_client.actual_creation_count == 1
