"""Lesson 10: extraction boundary demo backed by order_assistant."""

from order_assistant.application.extraction import (
    MISSING_FIELD_QUESTIONS,
    build_order_requirements,
)
from order_assistant.domain import (
    Brand,
    ExtractedOrder,
    ExtractionOutcome,
    OrderRequirements,
)
from order_assistant.infrastructure.extractors import MockOrderExtractor


def main() -> None:
    response_data = {
        "model": "6204", "quantity": 500, "primary_brand": "SKF",
        "fallback_brands": ["FAG"], "max_unit_price": "250",
        "delivery_deadline": "2026-08-15T09:00:00",
        "allow_split_fulfillment": False, "requires_clarification": False,
        "clarification_questions": [],
    }
    extracted = MockOrderExtractor(response_data).extract(
        "Нужно 500 подшипников SKF 6204 до 9 утра."
    )
    outcome = build_order_requirements(extracted)
    print("ExtractedOrder:")
    print(extracted)
    print("OrderRequirements:")
    print(outcome.requirements)


if __name__ == "__main__":
    main()
