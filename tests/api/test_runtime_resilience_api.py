import threading
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

from fastapi.testclient import TestClient

from order_assistant.api.app import create_app
from order_assistant.api.container import create_container
from order_assistant.application.runtime import LLMRuntimeController
from order_assistant.config import Settings
from order_assistant.domain import LLMRolloutMode
from order_assistant.infrastructure.extractors import MockOrderExtractor
from order_assistant.infrastructure.health import ReadinessService
from scripts.benchmark_ollama_concurrency import require_shadow


VALID = {
    "model": "6204",
    "quantity": 500,
    "primary_brand": "SKF",
    "fallback_brands": ["FAG"],
    "max_unit_price": "250",
    "delivery_deadline": "2026-08-17T09:00:00",
}
ADMIN = {"X-Demo-Actor-Id": "admin", "X-Demo-Actor-Role": "admin"}


class BlockingExtractor:
    def __init__(self) -> None:
        self.entered = threading.Event()
        self.release = threading.Event()
        self.calls = 0

    def extract(self, text):
        self.calls += 1
        self.entered.set()
        if not self.release.wait(timeout=2):
            raise AssertionError("test did not release extractor")
        return MockOrderExtractor(VALID).extract(text)


def test_capacity_error_has_retry_after_and_one_safe_audit() -> None:
    container = create_container(
        settings=Settings(
            extractor_backend="ollama",
            llm_rollout_mode="shadow",
            audit_hmac_key="test-key",
        ),
        order_extractor=MockOrderExtractor(VALID),
    )
    blocking = BlockingExtractor()
    runtime = LLMRuntimeController(
        blocking,
        max_concurrency=1,
        queue_capacity=0,
        queue_wait_timeout_seconds=1,
    )
    container.runtime_controller = runtime
    container.extraction_audit_service.extractor = runtime
    client = TestClient(create_app(container))
    with ThreadPoolExecutor(max_workers=1) as executor:
        first = executor.submit(
            container.extraction_audit_service.process_text,
            "first synthetic request",
            uuid4(),
        )
        assert blocking.entered.wait(timeout=1)
        response = client.post(
            "/api/v1/order-requests/from-text",
            json={"text": "second synthetic request"},
        )
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "llm_capacity_exceeded"
        assert response.headers["Retry-After"] == "1"
        blocking.release.set()
        first.result(timeout=1)
    audits = container.extraction_audit_repository.list_all()
    rejected = [audit for audit in audits if audit.capacity_rejected]
    assert len(audits) == 2 and len(rejected) == 1
    assert rejected[0].llm_error_code == "llm_capacity_exceeded"
    assert container.draft_repository._drafts == {}
    assert container.erp_client.actual_creation_count == 0


def test_runtime_summary_is_admin_only() -> None:
    container = create_container()
    client = TestClient(create_app(container))
    denied = client.get(
        "/api/v1/extraction-runtime/summary",
        headers={"X-Demo-Actor-Id": "manager", "X-Demo-Actor-Role": "manager"},
    )
    allowed = client.get("/api/v1/extraction-runtime/summary", headers=ADMIN)
    assert denied.status_code == 403
    assert allowed.status_code == 200
    assert allowed.json()["current_in_flight"] == 0


def test_liveness_never_calls_readiness_dependencies() -> None:
    container = create_container()

    class MustNotRun:
        def check(self):
            raise AssertionError("liveness called dependency probe")

        def close(self):
            pass

    container.readiness_service = MustNotRun()
    response = TestClient(create_app(container)).get("/health/live")
    assert response.status_code == 200


def test_readiness_probe_is_cached_without_sleep() -> None:
    calls = 0
    now = [0.0]

    def probe() -> bool:
        nonlocal calls
        calls += 1
        return True

    service = ReadinessService(
        rollout_mode=LLMRolloutMode.SHADOW,
        extractor_backend="ollama",
        cache_seconds=5,
        ollama_probe=probe,
        monotonic=lambda: now[0],
    )
    assert service.check()[0] is True
    ready, cached = service.check()
    assert ready is True and cached["cached"] is True and calls == 1
    now[0] = 6
    service.check()
    assert calls == 2


def test_benchmark_refuses_review_mode_without_network() -> None:
    try:
        require_shadow({"details": {"rollout_mode": "review"}})
    except RuntimeError as error:
        assert "requires shadow" in str(error)
    else:
        raise AssertionError("review benchmark was accepted")
