import hashlib
import os
import subprocess
import sys
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine, inspect, select

from order_assistant.api.app import create_app
from order_assistant.api.container import create_container
from order_assistant.config import Settings
from order_assistant.domain import (
    DraftStatus,
    ExtractedOrder,
    ExtractionReview,
    ExtractionReviewDecision,
)
from order_assistant.infrastructure.database.base import Base
from order_assistant.infrastructure.database.models import ExtractionAuditORM
from order_assistant.infrastructure.extractors import MockOrderExtractor
from scripts.export_extraction_feedback import build_feedback_rows, write_feedback


CANDIDATE = {
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
SOURCE = (
    "Нужно 500 подшипников SKF 6204 до 250 грн за штуку. "
    "Если SKF нет, можно FAG. Доставка 2026-08-15 09:00."
)
ADMIN = {"X-Demo-Actor-Id": "admin", "X-Demo-Actor-Role": "admin"}
MANAGER = {"X-Demo-Actor-Id": "manager", "X-Demo-Actor-Role": "manager"}


class FailingIfCalledExtractor:
    def extract(self, customer_message: str):
        raise AssertionError("disabled mode called the extractor")


def test_disabled_does_not_call_extractor() -> None:
    container = create_container(
        settings=Settings(llm_rollout_mode="disabled"),
        order_extractor=FailingIfCalledExtractor(),
    )
    response = TestClient(create_app(container)).post(
        "/api/v1/order-requests/from-text", json={"text": SOURCE}
    )
    assert response.status_code == 503
    assert container.extraction_audit_repository.list_all() == []


def _client(mode: str, candidate: dict | None = None):
    container = create_container(
        settings=Settings(
            extractor_backend="ollama",
            llm_rollout_mode=mode,
            audit_hmac_key="test-only-hmac-key",
        ),
        order_extractor=MockOrderExtractor(candidate or CANDIDATE),
    )
    return container, TestClient(create_app(container))


def test_shadow_only_creates_safe_audit_metadata() -> None:
    container, client = _client("shadow")
    response = client.post("/api/v1/order-requests/from-text", json={"text": SOURCE})

    assert response.status_code == 200
    assert response.json()["status"] == "shadow_processed"
    assert response.json()["draft_id"] is None
    assert container.draft_repository._drafts == {}
    assert container.submission_repository._submissions == {}
    assert container.erp_client.actual_creation_count == 0


def test_review_creates_unapproved_unsubmitted_draft() -> None:
    container, client = _client("review")
    response = client.post("/api/v1/order-requests/from-text", json={"text": SOURCE})

    assert response.status_code == 201
    assert response.json()["status"] == "draft_ready"
    draft = container.draft_repository.get(UUID(response.json()["draft_id"]))
    assert draft.status == DraftStatus.DRAFT_READY
    assert container.submission_repository._submissions == {}
    assert container.erp_client.actual_creation_count == 0


def test_fingerprint_is_keyed_and_stable() -> None:
    first, _ = _client("shadow")
    second, _ = _client("shadow")
    third = create_container(
        settings=Settings(
            extractor_backend="ollama",
            llm_rollout_mode="shadow",
            audit_hmac_key="other-key",
        ),
        order_extractor=MockOrderExtractor(CANDIDATE),
    )
    assert first.extraction_audit_service.fingerprint(SOURCE) == (
        second.extraction_audit_service.fingerprint(SOURCE)
    )
    assert first.extraction_audit_service.fingerprint(SOURCE) != (
        third.extraction_audit_service.fingerprint(SOURCE)
    )


@pytest.mark.parametrize("supplied", [str(uuid4()), "not-a-uuid"])
def test_request_id_is_accepted_or_generated(supplied: str) -> None:
    container, client = _client("shadow")
    response = client.post(
        "/api/v1/order-requests/from-text",
        json={"text": SOURCE},
        headers={"X-Request-ID": supplied},
    )
    request_id = UUID(response.headers["X-Request-ID"])
    assert container.extraction_audit_repository.list_all()[0].request_id == request_id
    if supplied != "not-a-uuid":
        assert str(request_id) == supplied


def test_audit_api_permissions_and_fingerprint_privacy() -> None:
    _, client = _client("shadow")
    created = client.post(
        "/api/v1/order-requests/from-text", json={"text": SOURCE}
    ).json()
    path = f"/api/v1/extraction-audits/{created['audit_id']}"

    for role in ("viewer", "manager", "operator"):
        response = client.get(
            path,
            headers={"X-Demo-Actor-Id": role, "X-Demo-Actor-Role": role},
        )
        assert response.status_code == 403
    response = client.get(path, headers=ADMIN)
    assert response.status_code == 200
    assert "source_fingerprint" not in response.text
    assert SOURCE not in response.text


def test_manager_can_review_but_viewer_and_operator_cannot() -> None:
    _, client = _client("shadow")
    audit_id = client.post(
        "/api/v1/order-requests/from-text", json={"text": SOURCE}
    ).json()["audit_id"]
    path = f"/api/v1/extraction-audits/{audit_id}/review"
    body = {"decision": "accepted"}
    for role in ("viewer", "operator"):
        denied = client.post(
            path,
            json=body,
            headers={"X-Demo-Actor-Id": role, "X-Demo-Actor-Role": role},
        )
        assert denied.status_code == 403
    accepted = client.post(path, json=body, headers=MANAGER)
    assert accepted.status_code == 200
    assert accepted.json()["reviewer_actor_id"] == "manager"


def test_review_validation_and_whitespace_normalization() -> None:
    with pytest.raises(ValidationError):
        ExtractionReview(
            audit_id=uuid4(),
            reviewer_actor_id="manager",
            reviewed_at="2026-08-16T10:00:00Z",
            decision="corrected",
        )
    with pytest.raises(ValidationError):
        ExtractionReview(
            audit_id=uuid4(),
            reviewer_actor_id="manager",
            reviewed_at="2026-08-16T10:00:00Z",
            decision="accepted",
            corrected_order=CANDIDATE,
        )
    review = ExtractionReview(
        audit_id=uuid4(),
        reviewer_actor_id="manager",
        reviewed_at="2026-08-16T10:00:00Z",
        decision="rejected",
        comment="  short\n  plain   comment ",
    )
    assert review.comment == "short plain comment"


def test_extraction_review_does_not_change_draft_status() -> None:
    container, client = _client("review")
    created = client.post(
        "/api/v1/order-requests/from-text", json={"text": SOURCE}
    ).json()
    client.post(
        f"/api/v1/extraction-audits/{created['audit_id']}/review",
        json={"decision": "rejected"},
        headers=MANAGER,
    )
    assert container.draft_repository.get(UUID(created["draft_id"])).status == (
        DraftStatus.DRAFT_READY
    )


def test_summary_aggregates_modes_outcomes_reviews_and_latency() -> None:
    container, client = _client("shadow")
    first = client.post(
        "/api/v1/order-requests/from-text", json={"text": SOURCE}
    ).json()
    client.post(
        f"/api/v1/extraction-audits/{first['audit_id']}/review",
        json={
            "decision": "corrected",
            "corrected_order": CANDIDATE,
            "correction_codes": ["quantity"],
        },
        headers=MANAGER,
    )
    second = container.extraction_audit_repository.get(UUID(first["audit_id"]))
    container.extraction_audit_repository.save(
        second.model_copy(
            update={"audit_id": uuid4(), "request_id": uuid4(), "latency_ms": 100}
        )
    )
    summary = client.get(
        "/api/v1/extraction-audits/summary", headers=ADMIN
    ).json()
    assert summary["total_extraction_attempts"] == 2
    assert summary["rollout_mode_counts"] == {"shadow": 2}
    assert summary["processing_outcome_counts"] == {"shadow_processed": 2}
    assert summary["review_decision_counts"] == {"corrected": 1}
    assert summary["review_correction_rate"] == 1.0
    assert summary["latency_ms_p95"] == 100


def test_sql_persistence_contains_no_source_candidate_or_thinking(tmp_path: Path) -> None:
    database = tmp_path / "audit.db"
    settings = Settings(
        persistence_backend="sqlalchemy",
        database_url=f"sqlite:///{database}",
        extractor_backend="ollama",
        llm_rollout_mode="shadow",
        audit_hmac_key="sql-test-key",
    )
    candidate = {
        **CANDIDATE,
        "clarification_questions": ["RAW_CANDIDATE THINKING_SECRET"],
    }
    container = create_container(
        settings=settings,
        order_extractor=MockOrderExtractor(candidate),
    )
    Base.metadata.create_all(container.engine)
    response = TestClient(create_app(container)).post(
        "/api/v1/order-requests/from-text", json={"text": SOURCE + " SOURCE_SECRET"}
    )
    assert response.status_code == 200
    with container.engine.connect() as connection:
        row = connection.execute(select(ExtractionAuditORM)).mappings().one()
        persisted = repr(dict(row))
    assert "SOURCE_SECRET" not in persisted
    assert "RAW_CANDIDATE" not in persisted
    assert "THINKING_SECRET" not in persisted


def test_export_only_corrected_and_does_not_touch_frozen_datasets(
    tmp_path: Path,
) -> None:
    frozen = [
        Path("evals/datasets/rfq_dev_v1.json"),
        Path("evals/datasets/rfq_holdout_v1.json"),
        Path("evals/manifests/rfq_holdout_v1.sha256"),
    ]
    existing = [path for path in frozen if path.exists()]
    before = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in existing}
    container, client = _client("shadow")
    audit_id = client.post(
        "/api/v1/order-requests/from-text", json={"text": SOURCE}
    ).json()["audit_id"]
    client.post(
        f"/api/v1/extraction-audits/{audit_id}/review",
        json={
            "decision": "corrected",
            "corrected_order": CANDIDATE,
            "correction_codes": ["quantity"],
        },
        headers=MANAGER,
    )
    rows = build_feedback_rows(
        container.extraction_audit_repository.list_all(),
        container.extraction_review_repository.list_all(),
    )
    output = tmp_path / "feedback.jsonl"
    write_feedback(rows, output)
    exported = output.read_text(encoding="utf-8")
    assert len(rows) == 1 and "corrected_order" in exported
    assert SOURCE not in exported and "source_fingerprint" not in exported
    after = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in existing}
    assert before == after


def test_alembic_upgrade_and_downgrade(tmp_path: Path) -> None:
    database = tmp_path / "migration.db"
    env = {**os.environ, "ORDER_ASSISTANT_DATABASE_URL": f"sqlite:///{database}"}
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=Path(__file__).parents[1],
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    engine = create_engine(f"sqlite:///{database}")
    assert {"extraction_audits", "extraction_reviews"}.issubset(
        inspect(engine).get_table_names()
    )
    engine.dispose()
    subprocess.run(
        [sys.executable, "-m", "alembic", "downgrade", "base"],
        cwd=Path(__file__).parents[1],
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    engine = create_engine(f"sqlite:///{database}")
    assert inspect(engine).get_table_names() == ["alembic_version"]
    engine.dispose()


def test_import_lesson_18_is_silent() -> None:
    result = subprocess.run(
        [sys.executable, "-c", "import lesson_18"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert result.stdout == "" and result.stderr == ""
