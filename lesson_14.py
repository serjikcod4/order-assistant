"""Lesson 14: optional local Ollama extraction boundary."""

from order_assistant.config import Settings
from order_assistant.infrastructure.extractors import OllamaOrderExtractor


def main() -> None:
    settings = Settings()
    extractor = OllamaOrderExtractor(
        settings.ollama_base_url,
        settings.ollama_model,
        settings.ollama_timeout_seconds,
    )
    try:
        extracted = extractor.extract(
            "Нужно 500 подшипников SKF 6204, не дороже 250 грн за штуку. "
            "Если SKF нет, можно FAG. Доставка до 2026-08-15 09:00."
        )
        print(extracted)
    finally:
        extractor.close()


if __name__ == "__main__":
    main()
