"""Lesson 15: evaluate versioned Ollama extraction prompts."""

from pathlib import Path

from order_assistant.evaluation import score_records, values_equal, write_reports
from order_assistant.infrastructure.ollama_prompts import get_prompt

__all__ = ["get_prompt", "score_records", "values_equal", "write_reports"]


def main() -> None:
    report_path = Path(__file__).parent / "eval_reports" / "ollama_ab.md"
    if report_path.exists():
        print(report_path.read_text(encoding="utf-8"))
        return
    print(
        "Run scripts/evaluate_ollama_extractor.py against local Ollama "
        "to create the lesson 15 report."
    )


if __name__ == "__main__":
    main()
