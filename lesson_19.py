"""Lesson 19: bounded runtime resilience for the local Ollama adapter."""

from order_assistant.application.runtime import (
    LLMRuntimeController,
    RuntimeCallMetrics,
)
from order_assistant.domain import CircuitState
from order_assistant.infrastructure.extractors import MockOrderExtractor


__all__ = [
    "CircuitState",
    "LLMRuntimeController",
    "RuntimeCallMetrics",
    "main",
]


def main() -> None:
    extractor = MockOrderExtractor(
        {
            "model": "6204",
            "quantity": 500,
            "primary_brand": "SKF",
            "fallback_brands": ["FAG"],
            "max_unit_price": "250",
            "delivery_deadline": "2026-08-17T09:00:00",
        }
    )
    controller = LLMRuntimeController(
        extractor,
        max_concurrency=1,
        queue_capacity=1,
    )
    result = controller.extract("offline demo input")
    print("result:", result)
    print("call metrics:", controller.last_call_metrics)
    print("runtime summary:", controller.snapshot())


if __name__ == "__main__":
    main()
