from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import inspect

from order_assistant.application.drafts import DraftService
from order_assistant.application.workflow import process_extracted_order
from order_assistant.domain import DraftStatus, IdempotencyKeyConflictError
from order_assistant.infrastructure.database.base import Base
from order_assistant.infrastructure.database.repositories import (
    SqlAlchemyDraftRepository,
    SqlAlchemySubmissionRepository,
)
from order_assistant.infrastructure.database.session import create_engine_and_session_factory
from order_assistant.infrastructure.demo_data import demo_inventory
from order_assistant.infrastructure.erp import FakeERPClient
from order_assistant.domain import ExtractedOrder


def repositories(tmp_path: Path):
    engine, session_factory = create_engine_and_session_factory(
        f"sqlite:///{tmp_path / 'repository.db'}"
    )
    Base.metadata.create_all(engine)
    return engine, SqlAlchemyDraftRepository(session_factory), SqlAlchemySubmissionRepository(session_factory)


def draft():
    result = process_extracted_order(
        ExtractedOrder.model_validate({
            "model": "6204", "quantity": 500, "primary_brand": "SKF",
            "fallback_brands": ["FAG"], "max_unit_price": "250",
            "delivery_deadline": "2026-08-15T09:00:00",
        }),
        demo_inventory,
    )
    return result


def test_sql_draft_round_trip_preserves_nested_result_and_update(tmp_path: Path) -> None:
    engine, drafts, _ = repositories(tmp_path)
    service = DraftService(drafts, FakeERPClient())
    created = service.create_draft(draft())
    approved = service.approve_draft(created.draft_id, "manager@example.com")
    restored = drafts.get(created.draft_id)

    assert restored.processing_result.selected_item.sku == "SKU-23"
    assert restored.processing_result.total_price == 120000
    assert restored.status == DraftStatus.APPROVED
    assert restored.approved_by == "manager@example.com"
    assert restored.created_at.tzinfo is not None
    engine.dispose()


def test_sql_submission_unique_constraints(tmp_path: Path) -> None:
    engine, drafts, submissions = repositories(tmp_path)
    service = DraftService(drafts, FakeERPClient())
    created = service.create_draft(draft())
    approved = service.approve_draft(created.draft_id, "manager@example.com")
    from order_assistant.application.submissions import ResilientOrderService
    from order_assistant.infrastructure.erp import ResilientFakeERPClient

    submission_service = ResilientOrderService(drafts, submissions, ResilientFakeERPClient())
    submission = submission_service.submit_approved_draft(approved.draft_id, "key-1")
    restored = submissions.find_by_draft_id(approved.draft_id)
    assert restored.attempt_count == 1
    assert restored.correlation_id == submission.correlation_id
    assert restored.erp_backend == "fake"
    assert restored.erp_contract_version == "v1"
    duplicate = submission.model_copy(
        update={"submission_id": uuid4(), "idempotency_key": "key-1"}
    )
    with pytest.raises(IdempotencyKeyConflictError):
        submissions.save(duplicate)
    engine.dispose()


def test_sql_metadata_has_required_tables_and_indexes(tmp_path: Path) -> None:
    engine, _, _ = repositories(tmp_path)
    names = inspect(engine).get_table_names()
    indexes = inspect(engine).get_indexes("order_submissions")

    assert {"order_drafts", "order_submissions"}.issubset(names)
    assert {index["name"] for index in indexes} == {
        "ix_order_submissions_status", "ix_order_submissions_updated_at"
    }
    engine.dispose()
