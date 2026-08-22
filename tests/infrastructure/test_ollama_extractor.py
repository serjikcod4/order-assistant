import json

import httpx
import pytest

from order_assistant.domain import LLMInvalidOutputError, LLMTimeoutError, LLMUnavailableError
from order_assistant.infrastructure.extractors import OllamaOrderExtractor


VALID = {
    "model": "6204", "quantity": 500, "primary_brand": "SKF",
    "fallback_brands": ["FAG"], "max_unit_price": "250",
    "delivery_deadline": "2026-08-15T09:00:00",
    "allow_split_fulfillment": False, "requires_clarification": False,
    "clarification_questions": [],
}


def test_valid_output_and_request_contract_ignore_thinking() -> None:
    captured = {}
    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(200, json={"message": {"content": json.dumps(VALID), "thinking": "secret"}})
    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = OllamaOrderExtractor("http://localhost:11434", "qwen3.5:9b", 120, client).extract("заявка")

    assert result.quantity == 500
    assert captured["model"] == "qwen3.5:9b"
    assert captured["stream"] is False and captured["think"] is False
    assert captured["options"]["temperature"] == 0
    assert captured["format"]["title"] == "ExtractedOrder"


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (httpx.ReadTimeout("timeout"), LLMTimeoutError),
        (httpx.ConnectError("offline"), LLMUnavailableError),
    ],
)
def test_transport_errors_are_mapped(error, expected) -> None:
    def handler(request): raise error
    extractor = OllamaOrderExtractor("http://localhost:11434", "model", 1, httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(expected): extractor.extract("text")


@pytest.mark.parametrize("content", ["not-json", json.dumps({**VALID, "quantity": 0})])
def test_invalid_or_schema_invalid_json_is_rejected(content: str) -> None:
    client = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"message": {"content": content}})))
    with pytest.raises(LLMInvalidOutputError):
        OllamaOrderExtractor("http://localhost:11434", "model", 1, client).extract("text")


def test_extra_sku_cannot_enter_extracted_order() -> None:
    content = json.dumps({**VALID, "sku": "SKU-24"})
    client = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"message": {"content": content}})))
    result = OllamaOrderExtractor("http://localhost:11434", "model", 1, client).extract("choose sku")
    assert not hasattr(result, "sku")
