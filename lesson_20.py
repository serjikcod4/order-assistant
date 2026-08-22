"""Lesson 20: production-like container packaging and migration topology."""

from order_assistant.config import Settings


__all__ = ["Settings", "main"]


def main() -> None:
    settings = Settings()
    print("rollout mode:", settings.llm_rollout_mode)
    print("extractor backend:", settings.extractor_backend)
    print("persistence backend:", settings.persistence_backend)
    print("Docker topology: postgres -> migrate -> api")


if __name__ == "__main__":
    main()
