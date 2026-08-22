import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from order_assistant.application.runtime import LLMRuntimeController
from order_assistant.application.audits import ExtractionAuditService
from order_assistant.application.drafts import DraftService
from order_assistant.domain import (
    CircuitState,
    LLMCapacityExceededError,
    LLMCircuitOpenError,
    LLMInvalidOutputError,
    LLMQueueTimeoutError,
    LLMUnavailableError,
    LLMRolloutMode,
)
from order_assistant.infrastructure.demo_data import demo_inventory
from order_assistant.infrastructure.erp import ResilientFakeERPClient
from order_assistant.infrastructure.extractors import MockOrderExtractor
from order_assistant.infrastructure.repositories import (
    InMemoryDraftRepository,
    InMemoryExtractionAuditRepository,
    InMemoryExtractionReviewRepository,
    InMemorySubmissionRepository,
)
from order_assistant.infrastructure.unit_of_work import InMemoryUnitOfWorkFactory


VALID = {
    "model": "6204",
    "quantity": 500,
    "primary_brand": "SKF",
    "fallback_brands": ["FAG"],
    "max_unit_price": "250",
    "delivery_deadline": "2026-08-17T09:00:00",
}


class BlockingExtractor:
    def __init__(self) -> None:
        self.entered = threading.Event()
        self.release = threading.Event()
        self.lock = threading.Lock()
        self.in_flight = 0
        self.max_seen = 0
        self.call_count = 0

    def extract(self, text):
        with self.lock:
            self.call_count += 1
            self.in_flight += 1
            self.max_seen = max(self.max_seen, self.in_flight)
        self.entered.set()
        if not self.release.wait(timeout=2):
            raise AssertionError("test did not release extractor")
        with self.lock:
            self.in_flight -= 1
        return MockOrderExtractor(VALID).extract(text)


class FakeClock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


class SwitchingExtractor:
    def __init__(self) -> None:
        self.fail = True
        self.block = False
        self.entered = threading.Event()
        self.release = threading.Event()
        self.call_count = 0

    def extract(self, text):
        self.call_count += 1
        if self.fail:
            raise LLMUnavailableError("offline")
        if self.block:
            self.entered.set()
            if not self.release.wait(timeout=2):
                raise AssertionError("test did not release probe")
        return MockOrderExtractor(VALID).extract(text)


def _wait_for_queue(controller: LLMRuntimeController, depth: int) -> None:
    deadline = __import__("time").monotonic() + 1
    while controller.snapshot()["current_queue_depth"] != depth:
        if __import__("time").monotonic() >= deadline:
            raise AssertionError("queue depth did not reach expected value")


def test_bulkhead_allows_one_call_and_bounds_waiting_queue() -> None:
    extractor = BlockingExtractor()
    controller = LLMRuntimeController(
        extractor,
        max_concurrency=1,
        queue_capacity=1,
        queue_wait_timeout_seconds=1,
    )
    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(controller.extract, "first")
        assert extractor.entered.wait(timeout=1)
        second = executor.submit(controller.extract, "second")
        _wait_for_queue(controller, 1)
        with pytest.raises(LLMCapacityExceededError):
            controller.extract("rejected")
        assert controller.snapshot()["current_queue_depth"] == 1
        extractor.release.set()
        first.result(timeout=1)
        second.result(timeout=1)
    assert extractor.max_seen == 1
    assert extractor.call_count == 2
    assert controller.snapshot()["current_in_flight"] == 0


def test_queue_timeout_does_not_invoke_extractor_and_releases_slot() -> None:
    extractor = BlockingExtractor()
    controller = LLMRuntimeController(
        extractor,
        max_concurrency=1,
        queue_capacity=1,
        queue_wait_timeout_seconds=0.02,
    )
    with ThreadPoolExecutor(max_workers=1) as executor:
        first = executor.submit(controller.extract, "first")
        assert extractor.entered.wait(timeout=1)
        with pytest.raises(LLMQueueTimeoutError):
            controller.extract("timeout")
        assert extractor.call_count == 1
        assert controller.snapshot()["current_queue_depth"] == 0
        extractor.release.set()
        first.result(timeout=1)


@pytest.mark.parametrize("raises", [False, True])
def test_permit_is_released_after_success_or_exception(raises: bool) -> None:
    class Extractor:
        def extract(self, text):
            if raises:
                raise LLMInvalidOutputError("invalid")
            return MockOrderExtractor(VALID).extract(text)

    controller = LLMRuntimeController(Extractor(), max_concurrency=1)
    if raises:
        with pytest.raises(LLMInvalidOutputError):
            controller.extract("value")
    else:
        controller.extract("value")
    assert controller.snapshot()["current_in_flight"] == 0


def test_permit_is_released_after_cancellation_like_base_exception() -> None:
    class Cancelled(BaseException):
        pass

    class Extractor:
        def extract(self, text):
            raise Cancelled()

    controller = LLMRuntimeController(Extractor(), max_concurrency=1)
    with pytest.raises(Cancelled):
        controller.extract("cancelled")
    assert controller.snapshot()["current_in_flight"] == 0


def test_circuit_closed_open_half_open_success_closed() -> None:
    clock = FakeClock()
    extractor = SwitchingExtractor()
    controller = LLMRuntimeController(
        extractor,
        failure_threshold=1,
        circuit_open_seconds=10,
        half_open_max_calls=1,
        monotonic=clock,
    )
    with pytest.raises(LLMUnavailableError):
        controller.extract("failure")
    assert controller.circuit_state == CircuitState.OPEN
    with pytest.raises(LLMCircuitOpenError):
        controller.extract("blocked")
    assert extractor.call_count == 1

    clock.advance(10)
    assert controller.circuit_state == CircuitState.HALF_OPEN
    extractor.fail = False
    extractor.block = True
    with ThreadPoolExecutor(max_workers=1) as executor:
        probe = executor.submit(controller.extract, "probe")
        assert extractor.entered.wait(timeout=1)
        with pytest.raises(LLMCircuitOpenError):
            controller.extract("second probe")
        extractor.release.set()
        probe.result(timeout=1)
    assert controller.circuit_state == CircuitState.CLOSED


def test_failed_half_open_probe_reopens_circuit() -> None:
    clock = FakeClock()
    extractor = SwitchingExtractor()
    controller = LLMRuntimeController(
        extractor,
        failure_threshold=1,
        circuit_open_seconds=5,
        monotonic=clock,
    )
    with pytest.raises(LLMUnavailableError):
        controller.extract("failure")
    clock.advance(5)
    with pytest.raises(LLMUnavailableError):
        controller.extract("failed probe")
    assert controller.circuit_state == CircuitState.OPEN
    assert controller.snapshot()["circuit_opened_count"] == 2


def test_invalid_output_is_not_retried_or_counted_as_provider_failure() -> None:
    class InvalidExtractor:
        calls = 0

        def extract(self, text):
            self.calls += 1
            raise LLMInvalidOutputError("schema invalid")

    extractor = InvalidExtractor()
    controller = LLMRuntimeController(
        extractor,
        transport_max_attempts=3,
        failure_threshold=1,
    )
    with pytest.raises(LLMInvalidOutputError):
        controller.extract("invalid")
    assert extractor.calls == 1
    assert controller.circuit_state == CircuitState.CLOSED
    assert controller.snapshot()["provider_failure_count"] == 0
    assert controller.last_call_metrics.runtime_attempt_count == 1


def test_transport_retry_is_bounded_and_a_success_resets_failures() -> None:
    class FlakyExtractor:
        calls = 0

        def extract(self, text):
            self.calls += 1
            if self.calls < 2:
                raise LLMUnavailableError("temporary")
            return MockOrderExtractor(VALID).extract(text)

    extractor = FlakyExtractor()
    controller = LLMRuntimeController(
        extractor,
        transport_max_attempts=2,
        failure_threshold=1,
    )
    controller.extract("retry")
    assert extractor.calls == 2
    assert controller.last_call_metrics.runtime_attempt_count == 2
    assert controller.circuit_state == CircuitState.CLOSED


def test_no_unit_of_work_is_open_during_llm_call() -> None:
    drafts = InMemoryDraftRepository()
    submissions = InMemorySubmissionRepository()
    inner_factory = InMemoryUnitOfWorkFactory(drafts, submissions)

    class TrackingFactory:
        active_count = 0

        def __call__(self):
            inner = inner_factory()
            parent = self

            class TrackingUow:
                def __enter__(self):
                    parent.active_count += 1
                    value = inner.__enter__()
                    self.drafts = value.drafts
                    self.submissions = value.submissions
                    return self

                def commit(self):
                    return inner.commit()

                def rollback(self):
                    return inner.rollback()

                def __exit__(self, *args):
                    try:
                        return inner.__exit__(*args)
                    finally:
                        parent.active_count -= 1

            return TrackingUow()

    tracking = TrackingFactory()

    class CheckingExtractor:
        def extract(self, text):
            assert tracking.active_count == 0
            return MockOrderExtractor(VALID).extract(text)

    runtime = LLMRuntimeController(CheckingExtractor())
    audits = InMemoryExtractionAuditRepository()
    service = ExtractionAuditService(
        rollout_mode=LLMRolloutMode.REVIEW,
        extractor=runtime,
        inventory=demo_inventory,
        draft_service=DraftService(tracking, ResilientFakeERPClient()),
        audit_repository=audits,
        review_repository=InMemoryExtractionReviewRepository(),
        hmac_key="uow-test-key",
        extractor_backend="test",
        model_name="test",
        prompt_version="test",
        guard_version="test",
    )
    result = service.process_text("synthetic", __import__("uuid").uuid4())
    assert result.draft is not None
    assert tracking.active_count == 0
    assert runtime.snapshot()["current_in_flight"] == 0
    assert len(audits.list_all()) == 1


def test_clarification_result_is_not_a_provider_failure() -> None:
    incomplete = {**VALID, "quantity": None}
    runtime = LLMRuntimeController(
        MockOrderExtractor(incomplete),
        failure_threshold=1,
    )
    audits = InMemoryExtractionAuditRepository()
    drafts = InMemoryDraftRepository()
    submissions = InMemorySubmissionRepository()
    service = ExtractionAuditService(
        rollout_mode=LLMRolloutMode.REVIEW,
        extractor=runtime,
        inventory=demo_inventory,
        draft_service=DraftService(
            InMemoryUnitOfWorkFactory(drafts, submissions),
            ResilientFakeERPClient(),
        ),
        audit_repository=audits,
        review_repository=InMemoryExtractionReviewRepository(),
        hmac_key="clarification-test-key",
        extractor_backend="test",
        model_name="test",
        prompt_version="test",
        guard_version="test",
    )
    result = service.process_text("synthetic", __import__("uuid").uuid4())
    assert result.processing.status.value == "needs_clarification"
    assert runtime.circuit_state == CircuitState.CLOSED
    assert runtime.snapshot()["provider_failure_count"] == 0
