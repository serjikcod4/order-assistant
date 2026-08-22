"""Lesson 17: frozen holdout evaluation and release quality gate."""

from order_assistant.evaluation.datasets import (
    load_dataset,
    verify_holdout_manifest,
)
from order_assistant.evaluation.release import (
    analyze_dataset,
    build_release_report,
    write_release_report,
)

__all__ = [
    "analyze_dataset",
    "build_release_report",
    "load_dataset",
    "verify_holdout_manifest",
    "write_release_report",
]


def main() -> None:
    manifest_hash = verify_holdout_manifest()
    print(f"Holdout cases: {len(load_dataset('holdout'))}")
    print(f"Manifest SHA-256: {manifest_hash}")
    print("Use scripts/evaluate_ollama_extractor.py --release for live evaluation.")


if __name__ == "__main__":
    main()
