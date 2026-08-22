from order_assistant.application.clarifications import (
    GROUNDING_QUESTION_ALIASES,
    MISSING_FIELD_QUESTIONS,
)
from order_assistant.domain import ExtractedOrder, ExtractionOutcome, OrderRequirements


def build_order_requirements(extracted: ExtractedOrder) -> ExtractionOutcome:
    """Build requirements only when every required field is available."""
    questions = list(dict.fromkeys(extracted.clarification_questions))
    missing_fields = [
        field_name
        for field_name in MISSING_FIELD_QUESTIONS
        if getattr(extracted, field_name) is None
    ]
    for field_name in missing_fields:
        question = MISSING_FIELD_QUESTIONS[field_name]
        equivalent_questions = GROUNDING_QUESTION_ALIASES[field_name] | {question}
        if not equivalent_questions.intersection(questions):
            questions.append(question)

    requires_clarification = (
        extracted.requires_clarification
        or bool(missing_fields)
        or bool(questions)
    )
    if missing_fields:
        return ExtractionOutcome(
            requirements=None,
            requires_clarification=requires_clarification,
            clarification_questions=questions,
        )

    requirements = OrderRequirements(
        model=extracted.model,
        quantity=extracted.quantity,
        primary_brand=extracted.primary_brand,
        fallback_brands=extracted.fallback_brands,
        max_unit_price=extracted.max_unit_price,
        delivery_deadline=extracted.delivery_deadline,
        allow_split_fulfillment=extracted.allow_split_fulfillment,
    )
    return ExtractionOutcome(
        requirements=requirements,
        requires_clarification=requires_clarification,
        clarification_questions=questions,
    )
