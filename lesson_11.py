"""Lesson 11: deterministic order workflow demo."""

from order_assistant.application.ports import OrderExtractor
from order_assistant.application.workflow import process_customer_order
from order_assistant.domain import (
    EvaluationResult,
    ExtractedOrder,
    InventoryItem,
    OrderProcessingResult,
    OrderProcessingStatus,
    OrderRequirements,
)
from order_assistant.application.extraction import build_order_requirements
from order_assistant.infrastructure.extractors import MockOrderExtractor


def main() -> None:
    from lesson_08 import inventory

    response_data = {
        "model": "6204", "quantity": 500, "primary_brand": "SKF",
        "fallback_brands": ["FAG"], "max_unit_price": "250",
        "delivery_deadline": "2026-08-15T09:00:00",
        "allow_split_fulfillment": False, "requires_clarification": False,
        "clarification_questions": [],
    }
    result = process_customer_order(
        "Нужно 500 подшипников SKF 6204.",
        MockOrderExtractor(response_data),
        inventory,
    )
    print(f"Статус: {result.status.value}")
    print(f"SKU: {result.selected_item.sku if result.selected_item else None}")
    print(f"Общая стоимость: {result.total_price}")
    print(f"Требуется подтверждение человека: {result.requires_human_approval}")


if __name__ == "__main__":
    main()
