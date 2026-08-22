"""Lesson 16: deterministic grounding of untrusted LLM extraction."""

from datetime import datetime, timezone

from order_assistant.application.grounding import ExtractionGroundingGuard
from order_assistant.domain import ExtractedOrder, GroundingIssueCode, GroundingResult

__all__ = [
    "ExtractionGroundingGuard",
    "GroundingIssueCode",
    "GroundingResult",
]


def main() -> None:
    raw_candidate = ExtractedOrder(
        model="6204",
        primary_brand="NSK",
        clarification_questions=["Уточните SKU-23"],
    )
    result = ExtractionGroundingGuard().guard(
        "Нужны подшипники NTN, модель не указана.",
        raw_candidate,
        datetime(2026, 8, 14, 12, 0, tzinfo=timezone.utc),
    )
    print(result.extracted)
    print([issue.code.value for issue in result.issues])


if __name__ == "__main__":
    main()
