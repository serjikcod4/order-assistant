import subprocess
import sys

import pytest

from lesson_08 import inventory
from lesson_10 import MockOrderExtractor
from lesson_11 import process_customer_order
from lesson_12 import DraftService, FakeERPClient, InMemoryDraftRepository
from lesson_13 import (
    ERPFailureMode,
    IdempotencyKeyConflictError,
    InMemorySubmissionRepository,
    InvalidSubmissionStateError,
    ResilientFakeERPClient,
    ResilientOrderService,
    SubmissionStatus,
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


def create_approved_draft():
    draft_repository = InMemoryDraftRepository()
    processing_result = process_customer_order(
        "Нужно 500 подшипников SKF 6204.",
        MockOrderExtractor(FULL_RESPONSE),
        inventory,
    )
    draft_service = DraftService(draft_repository, FakeERPClient())
    draft = draft_service.create_draft(processing_result)
    return draft_repository, draft_service.approve_draft(
        draft.draft_id,
        "manager@example.com",
    )


def create_submission_service(failure_mode: ERPFailureMode):
    draft_repository, draft = create_approved_draft()
    submission_repository = InMemorySubmissionRepository()
    erp_client = ResilientFakeERPClient(failure_mode)
    service = ResilientOrderService(
        draft_repository,
        submission_repository,
        erp_client,
    )
    return service, draft_repository, submission_repository, erp_client, draft


def test_submission_is_saved_before_erp_call() -> None:
    class ObservingERPClient(ResilientFakeERPClient):
        def __init__(self, repository: InMemorySubmissionRepository) -> None:
            super().__init__()
            self.repository = repository
            self.submission_was_saved = False

        def create_order(self, draft, idempotency_key):
            self.submission_was_saved = (
                self.repository.find_by_draft_id(draft.draft_id) is not None
            )
            return super().create_order(draft, idempotency_key)

    draft_repository, draft = create_approved_draft()
    submission_repository = InMemorySubmissionRepository()
    erp_client = ObservingERPClient(submission_repository)
    service = ResilientOrderService(
        draft_repository,
        submission_repository,
        erp_client,
    )

    service.submit_approved_draft(draft.draft_id, "submission-1")

    assert erp_client.submission_was_saved


def test_success_completes_submission() -> None:
    service, _, _, _, draft = create_submission_service(ERPFailureMode.SUCCESS)

    submission = service.submit_approved_draft(draft.draft_id, "submission-1")

    assert submission.status == SubmissionStatus.SUCCEEDED
    assert submission.created_order_id is not None


def test_draft_changes_only_after_confirmed_success() -> None:
    service, draft_repository, _, _, draft = create_submission_service(
        ERPFailureMode.TIMEOUT_BEFORE_CREATION
    )

    service.submit_approved_draft(draft.draft_id, "submission-1")

    assert draft_repository.get(draft.draft_id).status.value == "approved"


def test_timeout_before_creation_is_unknown_and_creates_no_order() -> None:
    service, _, _, erp_client, draft = create_submission_service(
        ERPFailureMode.TIMEOUT_BEFORE_CREATION
    )

    submission = service.submit_approved_draft(draft.draft_id, "submission-1")

    assert submission.status == SubmissionStatus.UNKNOWN
    assert erp_client.actual_creation_count == 0


def test_retry_after_timeout_before_creation_creates_one_order() -> None:
    service, _, _, erp_client, draft = create_submission_service(
        ERPFailureMode.TIMEOUT_BEFORE_CREATION
    )
    submission = service.submit_approved_draft(draft.draft_id, "submission-1")
    erp_client.failure_mode = ERPFailureMode.SUCCESS

    retried_submission = service.retry_submission(submission.submission_id)

    assert retried_submission.status == SubmissionStatus.SUCCEEDED
    assert erp_client.actual_creation_count == 1


def test_timeout_after_creation_is_unknown() -> None:
    service, _, _, _, draft = create_submission_service(
        ERPFailureMode.TIMEOUT_AFTER_CREATION
    )

    submission = service.submit_approved_draft(draft.draft_id, "submission-1")

    assert submission.status == SubmissionStatus.UNKNOWN


def test_timeout_after_creation_leaves_one_erp_order() -> None:
    service, _, _, erp_client, draft = create_submission_service(
        ERPFailureMode.TIMEOUT_AFTER_CREATION
    )

    service.submit_approved_draft(draft.draft_id, "submission-1")

    assert erp_client.actual_creation_count == 1


def test_retry_with_same_key_after_timeout_after_creation_creates_no_duplicate() -> None:
    service, _, _, erp_client, draft = create_submission_service(
        ERPFailureMode.TIMEOUT_AFTER_CREATION
    )
    submission = service.submit_approved_draft(draft.draft_id, "submission-1")

    retried_submission = service.retry_submission(submission.submission_id)

    assert retried_submission.status == SubmissionStatus.SUCCEEDED
    assert erp_client.actual_creation_count == 1


def test_reconciliation_finds_order_created_before_timeout() -> None:
    service, _, _, _, draft = create_submission_service(
        ERPFailureMode.TIMEOUT_AFTER_CREATION
    )
    submission = service.submit_approved_draft(draft.draft_id, "submission-1")

    reconciled_submission = service.reconcile_submission(submission.submission_id)

    assert reconciled_submission.created_order_id is not None


def test_reconciliation_moves_draft_to_order_created() -> None:
    service, draft_repository, _, _, draft = create_submission_service(
        ERPFailureMode.TIMEOUT_AFTER_CREATION
    )
    submission = service.submit_approved_draft(draft.draft_id, "submission-1")

    service.reconcile_submission(submission.submission_id)

    assert draft_repository.get(draft.draft_id).status.value == "order_created"


def test_new_idempotency_key_for_existing_draft_is_rejected() -> None:
    service, _, _, _, draft = create_submission_service(
        ERPFailureMode.TIMEOUT_BEFORE_CREATION
    )
    service.submit_approved_draft(draft.draft_id, "submission-1")

    with pytest.raises(IdempotencyKeyConflictError):
        service.submit_approved_draft(draft.draft_id, "submission-2")


def test_retry_uses_saved_idempotency_key() -> None:
    service, _, _, erp_client, draft = create_submission_service(
        ERPFailureMode.TIMEOUT_BEFORE_CREATION
    )
    submission = service.submit_approved_draft(draft.draft_id, "submission-1")
    erp_client.failure_mode = ERPFailureMode.SUCCESS

    service.retry_submission(submission.submission_id)

    assert erp_client.get_order_by_idempotency_key("submission-1") is not None


def test_permanent_failure_does_not_create_order() -> None:
    service, _, _, erp_client, draft = create_submission_service(
        ERPFailureMode.PERMANENT_FAILURE
    )

    submission = service.submit_approved_draft(draft.draft_id, "submission-1")

    assert submission.status == SubmissionStatus.PERMANENTLY_FAILED
    assert erp_client.actual_creation_count == 0


def test_permanently_failed_submission_cannot_be_retried() -> None:
    service, _, _, _, draft = create_submission_service(
        ERPFailureMode.PERMANENT_FAILURE
    )
    submission = service.submit_approved_draft(draft.draft_id, "submission-1")

    with pytest.raises(InvalidSubmissionStateError):
        service.retry_submission(submission.submission_id)


def test_unapproved_draft_cannot_be_submitted() -> None:
    draft_repository, draft = create_approved_draft()
    draft.status = draft.status.DRAFT_READY
    draft_repository.save(draft)
    service = ResilientOrderService(
        draft_repository,
        InMemorySubmissionRepository(),
        ResilientFakeERPClient(),
    )

    with pytest.raises(InvalidSubmissionStateError):
        service.submit_approved_draft(draft.draft_id, "submission-1")


def test_importing_lesson_13_produces_no_output() -> None:
    result = subprocess.run(
        [sys.executable, "-c", "import lesson_13"],
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.stdout == ""
    assert result.stderr == ""
