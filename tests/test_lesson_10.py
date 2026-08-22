from datetime import datetime
from decimal import Decimal
import subprocess
import sys

import pytest
from pydantic import ValidationError

from lesson_08 import Brand
from lesson_10 import (
    MISSING_FIELD_QUESTIONS,
    ExtractedOrder,
    MockOrderExtractor,
    build_order_requirements,
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


def test_full_mock_response_creates_requirements() -> None:
    extracted = MockOrderExtractor(FULL_RESPONSE).extract("any message")
    outcome = build_order_requirements(extracted)

    assert outcome.requirements is not None
    assert not outcome.requires_clarification
    assert outcome.clarification_questions == []


def test_values_are_transferred_to_requirements() -> None:
    outcome = build_order_requirements(ExtractedOrder.model_validate(FULL_RESPONSE))
    requirements = outcome.requirements

    assert requirements is not None
    assert requirements.model == "6204"
    assert requirements.quantity == 500
    assert requirements.primary_brand == Brand.SKF
    assert requirements.fallback_brands == [Brand.FAG]
    assert requirements.max_unit_price == Decimal("250")
    assert requirements.delivery_deadline == datetime(2026, 8, 15, 9, 0)


def test_missing_maximum_price_requires_clarification() -> None:
    extracted = ExtractedOrder.model_validate({**FULL_RESPONSE, "max_unit_price": None})
    outcome = build_order_requirements(extracted)

    assert outcome.requirements is None
    assert MISSING_FIELD_QUESTIONS["max_unit_price"] in outcome.clarification_questions


def test_missing_delivery_deadline_requires_clarification() -> None:
    extracted = ExtractedOrder.model_validate(
        {**FULL_RESPONSE, "delivery_deadline": None}
    )
    outcome = build_order_requirements(extracted)

    assert outcome.requirements is None
    assert MISSING_FIELD_QUESTIONS["delivery_deadline"] in outcome.clarification_questions


def test_several_missing_fields_create_several_questions() -> None:
    extracted = ExtractedOrder.model_validate(
        {
            "fallback_brands": [],
            "allow_split_fulfillment": False,
            "requires_clarification": False,
            "clarification_questions": [],
        }
    )
    outcome = build_order_requirements(extracted)

    assert outcome.requirements is None
    assert outcome.requires_clarification
    assert outcome.clarification_questions == list(MISSING_FIELD_QUESTIONS.values())


def test_existing_clarification_questions_are_preserved() -> None:
    question = "Уточните допустимый тип упаковки."
    extracted = ExtractedOrder.model_validate(
        {**FULL_RESPONSE, "clarification_questions": [question]}
    )
    outcome = build_order_requirements(extracted)

    assert outcome.clarification_questions == [question]


def test_duplicate_clarification_questions_are_removed() -> None:
    question = MISSING_FIELD_QUESTIONS["max_unit_price"]
    extracted = ExtractedOrder.model_validate(
        {
            **FULL_RESPONSE,
            "max_unit_price": None,
            "clarification_questions": [question, question],
        }
    )
    outcome = build_order_requirements(extracted)

    assert outcome.clarification_questions.count(question) == 1


def test_zero_quantity_is_rejected_by_pydantic() -> None:
    with pytest.raises(ValidationError):
        ExtractedOrder.model_validate({**FULL_RESPONSE, "quantity": 0})


def test_negative_maximum_price_is_rejected_by_pydantic() -> None:
    with pytest.raises(ValidationError):
        ExtractedOrder.model_validate({**FULL_RESPONSE, "max_unit_price": "-1"})


def test_importing_lesson_10_produces_no_output() -> None:
    result = subprocess.run(
        [sys.executable, "-c", "import lesson_10"],
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.stdout == ""
    assert result.stderr == ""
