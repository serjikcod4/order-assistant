import threading
import time
from collections.abc import Callable

import httpx
from sqlalchemy import Engine, text

from order_assistant.domain import CircuitState, LLMRolloutMode


class ReadinessService:
    """Cached dependency readiness checks; never performs LLM generation."""

    def __init__(
        self,
        *,
        rollout_mode: LLMRolloutMode,
        extractor_backend: str,
        cache_seconds: float,
        database_probe: Callable[[], bool] | None = None,
        ollama_probe: Callable[[], bool] | None = None,
        circuit_state: Callable[[], CircuitState] | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        close_callback: Callable[[], None] | None = None,
    ) -> None:
        self.rollout_mode = rollout_mode
        self.extractor_backend = extractor_backend
        self.cache_seconds = cache_seconds
        self.database_probe = database_probe
        self.ollama_probe = ollama_probe
        self.circuit_state = circuit_state
        self._clock = monotonic
        self._close_callback = close_callback
        self._lock = threading.Lock()
        self._cached_at: float | None = None
        self._cached_result: tuple[bool, dict[str, object]] | None = None

    def check(self) -> tuple[bool, dict[str, object]]:
        with self._lock:
            now = self._clock()
            if (
                self._cached_result is not None
                and self._cached_at is not None
                and now - self._cached_at < self.cache_seconds
            ):
                ready, details = self._cached_result
                details = {**details, "cached": True}
                if (
                    self.circuit_state is not None
                    and self.circuit_state() == CircuitState.OPEN
                ):
                    details["circuit_state"] = CircuitState.OPEN.value
                    details["ollama"] = "circuit_open"
                    ready = False
                return ready, details

            details: dict[str, object] = {
                "configuration": "ok",
                "rollout_mode": self.rollout_mode.value,
                "extractor_backend": self.extractor_backend,
                "database": "not_configured",
                "ollama": "not_required",
                "circuit_state": "not_configured",
                "cached": False,
            }
            ready = True
            if self.database_probe is not None:
                try:
                    database_ready = self.database_probe()
                except Exception:
                    database_ready = False
                details["database"] = "ready" if database_ready else "unavailable"
                ready = ready and database_ready

            ollama_required = (
                self.rollout_mode != LLMRolloutMode.DISABLED
                and self.extractor_backend == "ollama"
            )
            if ollama_required:
                state = (
                    self.circuit_state()
                    if self.circuit_state is not None
                    else CircuitState.CLOSED
                )
                details["circuit_state"] = state.value
                if state == CircuitState.OPEN:
                    details["ollama"] = "circuit_open"
                    ready = False
                else:
                    try:
                        ollama_ready = bool(
                            self.ollama_probe and self.ollama_probe()
                        )
                    except Exception:
                        ollama_ready = False
                    details["ollama"] = (
                        "ready" if ollama_ready else "unavailable"
                    )
                    ready = ready and ollama_ready

            self._cached_at = now
            self._cached_result = (ready, details)
            return ready, dict(details)

    def close(self) -> None:
        if self._close_callback is not None:
            self._close_callback()


def database_probe(engine: Engine) -> Callable[[], bool]:
    def probe() -> bool:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return True

    return probe


def ollama_health_probe(
    base_url: str,
    timeout_seconds: float,
) -> tuple[Callable[[], bool], Callable[[], None]]:
    client = httpx.Client(timeout=min(timeout_seconds, 3.0))

    def probe() -> bool:
        response = client.get(f"{base_url.rstrip('/')}/api/tags")
        response.raise_for_status()
        return True

    return probe, client.close
