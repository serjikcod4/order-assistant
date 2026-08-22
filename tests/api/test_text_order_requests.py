from datetime import datetime, timezone

from fastapi.testclient import TestClient

from order_assistant.api.app import create_app
from order_assistant.api.container import create_container
from order_assistant.application.grounding import (
    ExtractionGroundingGuard,
    GroundedOrderExtractor,
)
from order_assistant.config import Settings
from order_assistant.infrastructure.extractors import MockOrderExtractor


VALID = {
    "model": "6204", "quantity": 500, "primary_brand": "SKF",
    "fallback_brands": ["FAG"], "max_unit_price": "250",
    "delivery_deadline": "2026-08-15T09:00:00",
    "allow_split_fulfillment": False, "requires_clarification": False,
    "clarification_questions": [],
}


def test_disabled_text_extractor_is_controlled() -> None:
    response = TestClient(create_app(create_container())).post(
        "/api/v1/order-requests/from-text", json={"text": "order"}
    )
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "extractor_disabled"


def test_injected_extractor_runs_existing_workflow() -> None:
    container = create_container(order_extractor=MockOrderExtractor(VALID))
    response = TestClient(create_app(container)).post(
        "/api/v1/order-requests/from-text", json={"text": "Нужно 500 SKF 6204"}
    )
    assert response.status_code == 201
    assert response.json()["processing"]["status"] == "draft_ready"
    assert response.json()["processing"]["selected_item"]["sku"] == "SKU-23"


def test_grounded_llm_path_removes_hallucination_before_workflow() -> None:
    raw = MockOrderExtractor(
        {
            **VALID,
            "model": "6204",
            "clarification_questions": ["Уточните SKU-23"],
        }
    )
    grounded = GroundedOrderExtractor(
        raw,
        ExtractionGroundingGuard(),
        clock=lambda: datetime(2026, 8, 14, 12, tzinfo=timezone.utc),
    )
    container = create_container(order_extractor=grounded)

    response = TestClient(create_app(container)).post(
        "/api/v1/order-requests/from-text",
        json={"text": "Нужно 500 подшипников SKF до 250 грн к 2026-08-15 09:00"},
    )

    processing = response.json()["processing"]
    assert processing["status"] == "needs_clarification"
    assert processing["clarification_questions"] == [
        "Укажите точную модель товара."
    ]
    assert "SKU-23" not in response.text


def test_ollama_container_uses_grounding_but_injected_mock_does_not() -> None:
    ollama_container = create_container(
        settings=Settings(extractor_backend="ollama")
    )
    mock = MockOrderExtractor(VALID)
    mock_container = create_container(order_extractor=mock)
    try:
        assert isinstance(ollama_container.order_extractor, GroundedOrderExtractor)
        assert mock_container.order_extractor is mock
    finally:
        ollama_container.dispose()
        mock_container.dispose()


def test_import_does_not_call_http_or_print() -> None:
    import subprocess
    import sys

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import order_assistant.infrastructure.extractors; "
            "import order_assistant.api.app; import lesson_14; import lesson_16",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout == "" and result.stderr == ""
