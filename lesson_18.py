"""Lesson 18: privacy-aware extraction audit and staged rollout."""

from order_assistant.api.container import create_container
from order_assistant.application.audits import (
    ExtractionAuditService,
    ExtractionRunResult,
)
from order_assistant.config import Settings
from order_assistant.domain import (
    ExtractionAuditRecord,
    ExtractionReview,
    LLMRolloutMode,
)
from order_assistant.infrastructure.extractors import MockOrderExtractor


__all__ = [
    "ExtractionAuditRecord",
    "ExtractionAuditService",
    "ExtractionReview",
    "ExtractionRunResult",
    "LLMRolloutMode",
    "main",
]


DEMO_RESULT = {
    "model": "6204",
    "quantity": 500,
    "primary_brand": "SKF",
    "fallback_brands": ["FAG"],
    "max_unit_price": "250",
    "delivery_deadline": "2026-08-17T09:00:00+03:00",
    "allow_split_fulfillment": False,
    "requires_clarification": False,
    "clarification_questions": [],
}
DEMO_TEXT = (
    "Нужно 500 подшипников SKF 6204, не дороже 250 грн за штуку. "
    "Если SKF нет, можно FAG. Доставка 2026-08-17 09:00+03:00."
)


def main() -> None:
    settings = Settings(
        extractor_backend="ollama",
        llm_rollout_mode="shadow",
        audit_hmac_key="lesson-18-local-demo-key",
    )
    container = create_container(
        settings=settings,
        order_extractor=MockOrderExtractor(DEMO_RESULT),
    )
    try:
        from uuid import uuid4

        result = container.extraction_audit_service.process_text(
            DEMO_TEXT,
            uuid4(),
        )
        print("status:", result.audit.processing_outcome.value)
        print("audit:", result.audit.model_dump(exclude={"source_fingerprint"}))
        print("guarded result:", result.extracted)
        print("draft created:", result.draft is not None)
    finally:
        container.dispose()


if __name__ == "__main__":
    main()
