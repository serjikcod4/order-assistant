from datetime import timezone

from order_assistant.domain import (
    EvaluationResult,
    InventoryItem,
    OrderRequirements,
    RejectionDetail,
    RejectionReason,
)


def evaluate_item(
    item: InventoryItem,
    requirements: OrderRequirements,
) -> EvaluationResult:
    reasons: list[RejectionDetail] = []
    allowed_brands = (requirements.primary_brand, *requirements.fallback_brands)

    if item.model != requirements.model:
        reasons.append(
            RejectionDetail(
                code=RejectionReason.MODEL_MISMATCH,
                actual=item.model,
                expected=requirements.model,
            )
        )
    if item.brand not in allowed_brands:
        reasons.append(
            RejectionDetail(
                code=RejectionReason.BRAND_NOT_ALLOWED,
                actual=item.brand.value,
                expected=", ".join(brand.value for brand in allowed_brands),
            )
        )
    if item.stock < requirements.quantity:
        reasons.append(
            RejectionDetail(
                code=RejectionReason.INSUFFICIENT_STOCK,
                actual=str(item.stock),
                expected=f">={requirements.quantity}",
            )
        )
    if item.unit_price > requirements.max_unit_price:
        reasons.append(
            RejectionDetail(
                code=RejectionReason.PRICE_TOO_HIGH,
                actual=str(item.unit_price),
                expected=f"<={requirements.max_unit_price}",
            )
        )
    available = item.delivery_available_at
    deadline = requirements.delivery_deadline
    if available.tzinfo is not None:
        available = available.astimezone(timezone.utc).replace(tzinfo=None)
    if deadline.tzinfo is not None:
        deadline = deadline.astimezone(timezone.utc).replace(tzinfo=None)
    if available > deadline:
        reasons.append(
            RejectionDetail(
                code=RejectionReason.DELIVERY_TOO_LATE,
                actual=str(item.delivery_available_at),
                expected=str(requirements.delivery_deadline),
            )
        )
    return EvaluationResult(item=item, accepted=not reasons, reasons=reasons)


def evaluate_inventory(
    inventory: list[InventoryItem],
    requirements: OrderRequirements,
) -> list[EvaluationResult]:
    return [evaluate_item(item, requirements) for item in inventory]


def select_best_item(
    evaluations: list[EvaluationResult],
    requirements: OrderRequirements,
) -> InventoryItem | None:
    accepted_items = [result.item for result in evaluations if result.accepted]
    primary_candidates = [
        item for item in accepted_items if item.brand == requirements.primary_brand
    ]
    if primary_candidates:
        return min(primary_candidates, key=lambda item: item.unit_price)
    fallback_candidates = [
        item
        for item in accepted_items
        if item.brand in requirements.fallback_brands
    ]
    if fallback_candidates:
        return min(fallback_candidates, key=lambda item: item.unit_price)
    return None


def find_best_item(
    inventory: list[InventoryItem],
    requirements: OrderRequirements,
) -> InventoryItem | None:
    return select_best_item(evaluate_inventory(inventory, requirements), requirements)


def format_rejection(detail: RejectionDetail) -> str:
    if detail.code == RejectionReason.MODEL_MISMATCH:
        return (
            "модель не соответствует запросу: "
            f"ожидалась {detail.expected}, получена {detail.actual}"
        )
    if detail.code == RejectionReason.BRAND_NOT_ALLOWED:
        return f"производитель {detail.actual} запрещён; разрешены: {detail.expected}"
    if detail.code == RejectionReason.INSUFFICIENT_STOCK:
        return (
            "недостаточно товара: "
            f"ожидалось {detail.expected}, доступно {detail.actual}"
        )
    if detail.code == RejectionReason.PRICE_TOO_HIGH:
        return (
            "цена превышает ограничение: "
            f"максимум {detail.expected}, фактически {detail.actual}"
        )
    if detail.code == RejectionReason.DELIVERY_TOO_LATE:
        return (
            "доставка слишком поздняя: "
            f"требуется до {detail.expected}, доступна {detail.actual}"
        )
    return "неизвестная причина отклонения"
