"""Lesson 08: inventory matching demo backed by order_assistant."""

from datetime import datetime
from decimal import Decimal

from order_assistant.application.matching import (
    evaluate_inventory,
    evaluate_item,
    find_best_item,
    format_rejection,
    select_best_item,
)
from order_assistant.domain import (
    Brand,
    EvaluationResult,
    InventoryItem,
    OrderRequirements,
    RejectionDetail,
    RejectionReason,
)


requirements = OrderRequirements(
    model="6204",
    quantity=500,
    primary_brand=Brand.SKF,
    fallback_brands=[Brand.FAG],
    max_unit_price=Decimal("250"),
    delivery_deadline=datetime(2026, 8, 15, 9, 0),
)

inventory = [
    InventoryItem(
        sku="SKU-21", brand=Brand.SKF, model="6204", stock=300,
        unit_price=Decimal("230"), delivery_available_at=datetime(2026, 8, 15, 8, 0),
    ),
    InventoryItem(
        sku="SKU-22", brand=Brand.SKF, model="6204", stock=400,
        unit_price=Decimal("270"), delivery_available_at=datetime(2026, 8, 15, 8, 0),
    ),
    InventoryItem(
        sku="SKU-23", brand=Brand.FAG, model="6204", stock=600,
        unit_price=Decimal("240"), delivery_available_at=datetime(2026, 8, 15, 8, 30),
    ),
    InventoryItem(
        sku="SKU-24", brand=Brand.NSK, model="6204", stock=1000,
        unit_price=Decimal("190"), delivery_available_at=datetime(2026, 8, 15, 7, 0),
    ),
]


def print_inventory_evaluation(
    items: list[InventoryItem], order_requirements: OrderRequirements
) -> None:
    print("Результаты проверки склада:")
    for result in evaluate_inventory(items, order_requirements):
        if result.accepted:
            print(f"{result.item.sku}: подходит")
            continue
        print(f"{result.item.sku}: отклонён")
        for detail in result.reasons:
            print(f"  — {format_rejection(detail)}")


def print_selected_item(
    selected_item: InventoryItem | None, order_requirements: OrderRequirements
) -> None:
    if selected_item is None:
        print("Подходящий товар не найден")
        return
    total_price = selected_item.unit_price * order_requirements.quantity
    print("Выбран товар:")
    print(f"SKU: {selected_item.sku}")
    print(f"Производитель: {selected_item.brand.value}")
    print(f"Модель: {selected_item.model}")
    print(f"Количество: {order_requirements.quantity}")
    print(f"Цена за штуку: {selected_item.unit_price} грн")
    print(f"Общая стоимость: {total_price} грн")


def main() -> None:
    print_inventory_evaluation(inventory, requirements)
    print()
    print_selected_item(find_best_item(inventory, requirements), requirements)


if __name__ == "__main__":
    main()
