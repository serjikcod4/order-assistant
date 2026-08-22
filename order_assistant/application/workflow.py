from decimal import Decimal

from order_assistant.application.extraction import build_order_requirements
from order_assistant.application.matching import evaluate_inventory, select_best_item
from order_assistant.application.ports import OrderExtractor
from order_assistant.domain import (
    ExtractedOrder,
    InventoryItem,
    OrderProcessingResult,
    OrderProcessingStatus,
)


def process_customer_order(
    customer_message: str,
    extractor: OrderExtractor,
    inventory: list[InventoryItem],
) -> OrderProcessingResult:
    extracted = extractor.extract(customer_message)
    return process_extracted_order(extracted, inventory)


def process_extracted_order(
    extracted: ExtractedOrder,
    inventory: list[InventoryItem],
) -> OrderProcessingResult:
    """Run the deterministic workflow after extraction has completed."""
    outcome = build_order_requirements(extracted)
    if outcome.requires_clarification:
        return OrderProcessingResult(
            status=OrderProcessingStatus.NEEDS_CLARIFICATION,
            requirements=None,
            selected_item=None,
            evaluations=[],
            clarification_questions=outcome.clarification_questions,
            total_price=None,
            requires_human_approval=True,
        )

    requirements = outcome.requirements
    if requirements is None:
        raise ValueError("Complete extraction must produce order requirements.")
    evaluations = evaluate_inventory(inventory, requirements)
    selected_item = select_best_item(evaluations, requirements)
    if selected_item is None:
        return OrderProcessingResult(
            status=OrderProcessingStatus.NO_MATCH,
            requirements=requirements,
            selected_item=None,
            evaluations=evaluations,
            clarification_questions=[],
            total_price=None,
            requires_human_approval=True,
        )
    return OrderProcessingResult(
        status=OrderProcessingStatus.DRAFT_READY,
        requirements=requirements,
        selected_item=selected_item,
        evaluations=evaluations,
        clarification_questions=[],
        total_price=selected_item.unit_price * requirements.quantity,
        requires_human_approval=True,
    )
