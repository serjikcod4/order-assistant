from datetime import datetime
from decimal import Decimal
import subprocess
import sys

from lesson_08 import Brand, InventoryItem, inventory
from lesson_10 import ExtractedOrder
from lesson_11 import (
    OrderProcessingStatus,
    process_customer_order,
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


class SpyExtractor:
    def __init__(self, response_data: dict[str, object]) -> None:
        self.response_data = response_data
        self.calls: list[str] = []

    def extract(self, customer_message: str) -> ExtractedOrder:
        self.calls.append(customer_message)
        return ExtractedOrder.model_validate(self.response_data)


def process(response_data: dict[str, object], items: list[InventoryItem] = inventory):
    return process_customer_order("Исходное письмо", SpyExtractor(response_data), items)


def test_complete_request_ends_with_draft_ready() -> None:
    assert process(FULL_RESPONSE).status == OrderProcessingStatus.DRAFT_READY


def test_sku_23_is_selected() -> None:
    assert process(FULL_RESPONSE).selected_item.sku == "SKU-23"


def test_total_price_is_calculated() -> None:
    assert process(FULL_RESPONSE).total_price == Decimal("120000")


def test_draft_requires_human_approval() -> None:
    assert process(FULL_RESPONSE).requires_human_approval


def test_incomplete_request_needs_clarification() -> None:
    result = process({**FULL_RESPONSE, "quantity": None})

    assert result.status == OrderProcessingStatus.NEEDS_CLARIFICATION


def test_clarification_has_no_selected_item() -> None:
    result = process({**FULL_RESPONSE, "delivery_deadline": None})

    assert result.selected_item is None


def test_clarification_has_empty_evaluations() -> None:
    result = process({**FULL_RESPONSE, "delivery_deadline": None})

    assert result.evaluations == []


def test_no_match_is_returned_when_no_item_is_accepted() -> None:
    result = process({**FULL_RESPONSE, "max_unit_price": "100"})

    assert result.status == OrderProcessingStatus.NO_MATCH


def test_no_match_preserves_inventory_evaluations() -> None:
    result = process({**FULL_RESPONSE, "max_unit_price": "100"})

    assert result.evaluations
    assert result.selected_item is None


def test_primary_brand_has_priority_over_cheaper_fallback() -> None:
    deadline = datetime(2026, 8, 15, 9, 0)
    items = [
        InventoryItem(
            sku="FAG-1",
            brand=Brand.FAG,
            model="6204",
            stock=500,
            unit_price=Decimal("200"),
            delivery_available_at=deadline,
        ),
        InventoryItem(
            sku="SKF-1",
            brand=Brand.SKF,
            model="6204",
            stock=500,
            unit_price=Decimal("250"),
            delivery_available_at=deadline,
        ),
    ]

    assert process(FULL_RESPONSE, items).selected_item.sku == "SKF-1"


def test_extractor_is_called_once() -> None:
    message = "Нужны подшипники"
    extractor = SpyExtractor(FULL_RESPONSE)

    process_customer_order(message, extractor, inventory)

    assert len(extractor.calls) == 1


def test_extractor_receives_original_message() -> None:
    message = "Нужны подшипники"
    extractor = SpyExtractor(FULL_RESPONSE)

    process_customer_order(message, extractor, inventory)

    assert extractor.calls == [message]


def test_importing_lesson_11_produces_no_output() -> None:
    result = subprocess.run(
        [sys.executable, "-c", "import lesson_11"],
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.stdout == ""
    assert result.stderr == ""
