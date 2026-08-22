import math
import threading
import time
from dataclasses import dataclass
from typing import Callable

from order_assistant.application.ports import OrderExtractor
from order_assistant.domain import (
    CircuitState,
    ExtractedOrder,
    LLMCircuitOpenError,
    LLMCapacityExceededError,
    LLMHTTPServerError,
    LLMMalformedResponseError,
    LLMQueueTimeoutError,
    LLMTimeoutError,
    LLMUnavailableError,
)


PROVIDER_FAILURES = (
    LLMUnavailableError,
    LLMTimeoutError,
    LLMHTTPServerError,
    LLMMalformedResponseError,
)
RETRYABLE_TRANSPORT_FAILURES = (
    LLMUnavailableError,
    LLMTimeoutError,
    LLMHTTPServerError,
)


@dataclass(frozen=True)
class RuntimeCallMetrics:
    queue_wait_ms: int = 0
    inference_ms: int = 0
    total_extraction_ms: int = 0
    runtime_attempt_count: int = 0
    circuit_state_at_start: CircuitState = CircuitState.CLOSED
    capacity_rejected: bool = False
    queue_timed_out: bool = False


class LLMRuntimeController:
    """Process-local bulkhead, bounded queue and circuit breaker."""

    def __init__(
        self,
        extractor: OrderExtractor,
        *,
        max_concurrency: int = 1,
        queue_capacity: int = 4,
        queue_wait_timeout_seconds: float = 5,
        failure_threshold: int = 3,
        circuit_open_seconds: float = 30,
        half_open_max_calls: int = 1,
        transport_max_attempts: int = 1,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if max_concurrency <= 0:
            raise ValueError("max_concurrency must be greater than zero.")
        if queue_capacity < 0:
            raise ValueError("queue_capacity cannot be negative.")
        if queue_wait_timeout_seconds <= 0:
            raise ValueError("queue_wait_timeout_seconds must be positive.")
        if failure_threshold <= 0 or half_open_max_calls <= 0:
            raise ValueError("Circuit limits must be greater than zero.")
        if circuit_open_seconds <= 0:
            raise ValueError("circuit_open_seconds must be positive.")
        if transport_max_attempts < 1:
            raise ValueError("transport_max_attempts must be at least one.")
        self.extractor = extractor
        self.max_concurrency = max_concurrency
        self.queue_capacity = queue_capacity
        self.queue_wait_timeout_seconds = queue_wait_timeout_seconds
        self.failure_threshold = failure_threshold
        self.circuit_open_seconds = circuit_open_seconds
        self.half_open_max_calls = half_open_max_calls
        self.transport_max_attempts = transport_max_attempts
        self._clock = monotonic
        self._condition = threading.Condition(threading.RLock())
        self._local = threading.local()
        self._in_flight = 0
        self._queue_depth = 0
        self._state = CircuitState.CLOSED
        self._opened_at: float | None = None
        self._consecutive_failures = 0
        self._half_open_in_flight = 0
        self._total_accepted = 0
        self._capacity_rejected = 0
        self._queue_timeout_count = 0
        self._provider_failure_count = 0
        self._circuit_open_rejection_count = 0
        self._circuit_opened_count = 0

    @property
    def last_call_metrics(self) -> RuntimeCallMetrics | None:
        return getattr(self._local, "metrics", None)

    @property
    def circuit_state(self) -> CircuitState:
        with self._condition:
            self._refresh_circuit_locked()
            return self._state

    def extract(self, customer_message: str) -> ExtractedOrder:
        started = self._clock()
        with self._condition:
            self._refresh_circuit_locked()
            state_at_start = self._state
            if self._state == CircuitState.OPEN:
                self._reject_circuit_locked(started, state_at_start)
            if (
                self._state == CircuitState.HALF_OPEN
                and self._half_open_in_flight >= self.half_open_max_calls
            ):
                self._reject_circuit_locked(started, state_at_start)

            queue_started = self._clock()
            if self._in_flight >= self.max_concurrency:
                if self._queue_depth >= self.queue_capacity:
                    self._capacity_rejected += 1
                    self._set_metrics(
                        started,
                        state_at_start,
                        capacity_rejected=True,
                    )
                    raise LLMCapacityExceededError(
                        "The local LLM queue is full.",
                        math.ceil(self.queue_wait_timeout_seconds),
                    )
                self._queue_depth += 1
                deadline = queue_started + self.queue_wait_timeout_seconds
                try:
                    while self._in_flight >= self.max_concurrency:
                        remaining = deadline - self._clock()
                        if remaining <= 0:
                            self._queue_timeout_count += 1
                            self._set_metrics(
                                started,
                                state_at_start,
                                queue_wait_ms=_milliseconds(
                                    self._clock() - queue_started
                                ),
                                queue_timed_out=True,
                            )
                            raise LLMQueueTimeoutError(
                                "Timed out waiting for local LLM capacity.",
                                math.ceil(self.queue_wait_timeout_seconds),
                            )
                        self._condition.wait(timeout=remaining)
                finally:
                    self._queue_depth -= 1

            queue_wait_ms = _milliseconds(self._clock() - queue_started)
            self._refresh_circuit_locked()
            if self._state == CircuitState.OPEN:
                self._reject_circuit_locked(
                    started,
                    state_at_start,
                    queue_wait_ms,
                )
            if self._state == CircuitState.HALF_OPEN:
                if self._half_open_in_flight >= self.half_open_max_calls:
                    self._reject_circuit_locked(
                        started,
                        state_at_start,
                        queue_wait_ms,
                    )
                self._half_open_in_flight += 1
                probe = True
            else:
                probe = False
            self._in_flight += 1
            self._total_accepted += 1

        inference_started = self._clock()
        attempts = 0
        try:
            while True:
                attempts += 1
                try:
                    result = self.extractor.extract(customer_message)
                    break
                except RETRYABLE_TRANSPORT_FAILURES:
                    if attempts >= self.transport_max_attempts:
                        raise
            inference_ms = _milliseconds(self._clock() - inference_started)
            with self._condition:
                self._record_success_locked(probe)
            self._set_metrics(
                started,
                state_at_start,
                queue_wait_ms=queue_wait_ms,
                inference_ms=inference_ms,
                attempts=attempts,
            )
            return result
        except PROVIDER_FAILURES:
            inference_ms = _milliseconds(self._clock() - inference_started)
            with self._condition:
                self._provider_failure_count += 1
                self._record_failure_locked(probe)
            self._set_metrics(
                started,
                state_at_start,
                queue_wait_ms=queue_wait_ms,
                inference_ms=inference_ms,
                attempts=attempts,
            )
            raise
        except BaseException:
            inference_ms = _milliseconds(self._clock() - inference_started)
            with self._condition:
                if probe:
                    self._half_open_in_flight = max(
                        0, self._half_open_in_flight - 1
                    )
            self._set_metrics(
                started,
                state_at_start,
                queue_wait_ms=queue_wait_ms,
                inference_ms=inference_ms,
                attempts=attempts,
            )
            raise
        finally:
            with self._condition:
                self._in_flight -= 1
                self._condition.notify_all()

    def snapshot(self) -> dict[str, object]:
        with self._condition:
            self._refresh_circuit_locked()
            return {
                "current_in_flight": self._in_flight,
                "current_queue_depth": self._queue_depth,
                "configured_max_concurrency": self.max_concurrency,
                "configured_queue_capacity": self.queue_capacity,
                "total_accepted": self._total_accepted,
                "capacity_rejected": self._capacity_rejected,
                "queue_timeout_count": self._queue_timeout_count,
                "provider_failure_count": self._provider_failure_count,
                "circuit_open_rejection_count": (
                    self._circuit_open_rejection_count
                ),
                "current_circuit_state": self._state.value,
                "circuit_opened_count": self._circuit_opened_count,
            }

    def _refresh_circuit_locked(self) -> None:
        if (
            self._state == CircuitState.OPEN
            and self._opened_at is not None
            and self._clock() - self._opened_at >= self.circuit_open_seconds
        ):
            self._state = CircuitState.HALF_OPEN
            self._half_open_in_flight = 0

    def _reject_circuit_locked(
        self,
        started: float,
        state_at_start: CircuitState,
        queue_wait_ms: int = 0,
    ) -> None:
        self._circuit_open_rejection_count += 1
        self._set_metrics(
            started,
            state_at_start,
            queue_wait_ms=queue_wait_ms,
        )
        remaining = self.circuit_open_seconds
        if self._state == CircuitState.OPEN and self._opened_at is not None:
            remaining -= self._clock() - self._opened_at
        raise LLMCircuitOpenError(
            "The local LLM circuit breaker is open.",
            math.ceil(max(1, remaining)),
        )

    def _record_success_locked(self, probe: bool) -> None:
        if probe:
            self._half_open_in_flight = max(0, self._half_open_in_flight - 1)
            self._state = CircuitState.CLOSED
            self._opened_at = None
        if self._state == CircuitState.CLOSED:
            self._consecutive_failures = 0

    def _record_failure_locked(self, probe: bool) -> None:
        if probe:
            self._half_open_in_flight = max(0, self._half_open_in_flight - 1)
            self._open_circuit_locked()
            return
        if self._state != CircuitState.CLOSED:
            return
        self._consecutive_failures += 1
        if self._consecutive_failures >= self.failure_threshold:
            self._open_circuit_locked()

    def _open_circuit_locked(self) -> None:
        if self._state != CircuitState.OPEN:
            self._circuit_opened_count += 1
        self._state = CircuitState.OPEN
        self._opened_at = self._clock()

    def _set_metrics(
        self,
        started: float,
        state_at_start: CircuitState,
        *,
        queue_wait_ms: int = 0,
        inference_ms: int = 0,
        attempts: int = 0,
        capacity_rejected: bool = False,
        queue_timed_out: bool = False,
    ) -> None:
        self._local.metrics = RuntimeCallMetrics(
            queue_wait_ms=queue_wait_ms,
            inference_ms=inference_ms,
            total_extraction_ms=_milliseconds(self._clock() - started),
            runtime_attempt_count=attempts,
            circuit_state_at_start=state_at_start,
            capacity_rejected=capacity_rejected,
            queue_timed_out=queue_timed_out,
        )

    def close(self) -> None:
        close = getattr(self.extractor, "close", None)
        if close is not None:
            close()


def _milliseconds(seconds: float) -> int:
    return max(0, round(seconds * 1000))
