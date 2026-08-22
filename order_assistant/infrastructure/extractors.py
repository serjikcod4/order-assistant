import httpx
from copy import deepcopy
from pydantic import ValidationError

from order_assistant.domain import ExtractedOrder
from order_assistant.domain import (
    LLMBadResponseError,
    LLMHTTPServerError,
    LLMInvalidOutputError,
    LLMMalformedResponseError,
    LLMTimeoutError,
    LLMUnavailableError,
)
from order_assistant.infrastructure.ollama_prompts import get_prompt


def _ollama_compatible_schema() -> dict:
    """Derive the schema from Pydantic and remove unsupported regex grammar."""
    schema = deepcopy(ExtractedOrder.model_json_schema())

    def clean(value: object) -> None:
        if isinstance(value, dict):
            value.pop("pattern", None)
            for child in value.values():
                clean(child)
        elif isinstance(value, list):
            for child in value:
                clean(child)

    clean(schema)
    return schema


class MockOrderExtractor:
    """Offline replacement for a future LLM-powered extractor."""

    def __init__(self, response_data: dict[str, object]) -> None:
        self.response_data = response_data

    def extract(self, customer_message: str) -> ExtractedOrder:
        del customer_message
        return ExtractedOrder.model_validate(self.response_data)


class OllamaOrderExtractor:
    """Local Ollama adapter that only produces a validated ExtractedOrder."""

    def __init__(
        self,
        base_url: str,
        model: str,
        timeout_seconds: float,
        client: httpx.Client | None = None,
        prompt_version: str = "v1",
        think: bool = False,
        current_datetime=None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self._owns_client = client is None
        self.client = client or httpx.Client(timeout=timeout_seconds)
        self.prompt_version = prompt_version
        self.think = think
        self.current_datetime = current_datetime

    def extract(self, customer_message: str) -> ExtractedOrder:
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": get_prompt(self.prompt_version, self.current_datetime),
                },
                {"role": "user", "content": customer_message},
            ],
            "stream": False,
            "think": self.think,
            "format": _ollama_compatible_schema(),
            "options": {"temperature": 0},
        }
        try:
            response = self.client.post(f"{self.base_url}/api/chat", json=payload)
            response.raise_for_status()
        except httpx.TimeoutException as error:
            raise LLMTimeoutError("Local Ollama request timed out.") from error
        except httpx.RequestError as error:
            raise LLMUnavailableError("Local Ollama is unavailable.") from error
        except httpx.HTTPStatusError as error:
            if error.response.status_code >= 500:
                raise LLMHTTPServerError(
                    "Ollama returned a server error."
                ) from error
            raise LLMBadResponseError("Ollama returned an unsuccessful HTTP status.") from error

        try:
            content = response.json()["message"]["content"]
        except (ValueError, KeyError, TypeError) as error:
            raise LLMMalformedResponseError(
                "Ollama response has an invalid structure."
            ) from error
        if not isinstance(content, str):
            raise LLMMalformedResponseError(
                "Ollama message content must be a JSON string."
            )
        try:
            return ExtractedOrder.model_validate_json(content)
        except ValidationError as error:
            raise LLMInvalidOutputError("Ollama output does not match ExtractedOrder.") from error

    def close(self) -> None:
        if self._owns_client:
            self.client.close()
