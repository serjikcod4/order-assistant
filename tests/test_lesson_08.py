from datetime import timedelta
from decimal import Decimal

from lesson_08 import (
    Brand,
    InventoryItem,
    OrderRequirements,
    RejectionReason,
    evaluate_item,
    find_best_item,
    inventory,
    requirements,
)


def create_item(**overrides: object) -> InventoryItem:
    values: dict[str, object] = {
        "sku": "test-sku",
        "brand": Brand.SKF,
        "model": requirements.model,
        "stock": requirements.quantity,
        "unit_price": requirements.max_unit_price,
        "delivery_available_at": requirements.delivery_deadline,
    }
    values.update(overrides)
    return InventoryItem(**values)


def test_sku_22_rejected_for_stock_and_price() -> None:
    result = evaluate_item(inventory[1], requirements)

    assert not result.accepted
    assert {detail.code for detail in result.reasons} == {
        RejectionReason.INSUFFICIENT_STOCK,
        RejectionReason.PRICE_TOO_HIGH,
    }


def test_sku_23_is_selected_when_no_skf_matches() -> None:
    assert find_best_item(inventory, requirements).sku == "SKU-23"


def test_matching_skf_is_selected_over_cheaper_fag() -> None:
    skf_item = create_item(sku="SKF-1", unit_price=Decimal("250"))
    fag_item = create_item(
        sku="FAG-1",
        brand=Brand.FAG,
        unit_price=Decimal("200"),
    )

    assert find_best_item([fag_item, skf_item], requirements) == skf_item


def test_nsk_is_rejected_as_brand_not_allowed() -> None:
    result = evaluate_item(inventory[3], requirements)

    assert RejectionReason.BRAND_NOT_ALLOWED in {
        detail.code for detail in result.reasons
    }


def test_delivery_after_deadline_is_rejected() -> None:
    item = create_item(
        delivery_available_at=requirements.delivery_deadline + timedelta(seconds=1)
    )
    result = evaluate_item(item, requirements)

    assert RejectionReason.DELIVERY_TOO_LATE in {
        detail.code for detail in result.reasons
    }


def test_delivery_at_deadline_is_allowed() -> None:
    result = evaluate_item(create_item(), requirements)

    assert result.accepted


def test_price_at_maximum_limit_is_allowed() -> None:
    item = create_item(unit_price=requirements.max_unit_price)
    result = evaluate_item(item, requirements)

    assert result.accepted
