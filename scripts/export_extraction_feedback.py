"""Export corrected extraction reviews without customer source text."""

import argparse
import json
from pathlib import Path

from order_assistant.api.container import create_container
from order_assistant.config import Settings
from order_assistant.domain import ExtractionReviewDecision


def build_feedback_rows(audits, reviews) -> list[dict[str, object]]:
    audits_by_id = {audit.audit_id: audit for audit in audits}
    rows = []
    for review in reviews:
        if review.decision != ExtractionReviewDecision.CORRECTED:
            continue
        audit = audits_by_id.get(review.audit_id)
        if audit is None or review.corrected_order is None:
            continue
        rows.append(
            {
                "audit_id": str(audit.audit_id),
                "request_id": str(audit.request_id),
                "audit_created_at": audit.created_at.isoformat(),
                "reviewed_at": review.reviewed_at.isoformat(),
                "reviewer_actor_id": review.reviewer_actor_id,
                "rollout_mode": audit.rollout_mode.value,
                "extractor_backend": audit.extractor_backend,
                "model_name": audit.model_name,
                "prompt_version": audit.prompt_version,
                "guard_version": audit.guard_version,
                "processing_outcome": audit.processing_outcome.value,
                "queue_wait_ms": audit.queue_wait_ms,
                "inference_ms": audit.inference_ms,
                "total_extraction_ms": audit.total_extraction_ms,
                "runtime_attempt_count": audit.runtime_attempt_count,
                "circuit_state_at_start": audit.circuit_state_at_start.value,
                "grounding_issue_codes": [
                    code.value for code in audit.grounding_issue_codes
                ],
                "correction_codes": [
                    code.value for code in review.correction_codes
                ],
                "corrected_order": review.corrected_order.model_dump(mode="json"),
            }
        )
    return rows


def write_feedback(rows: list[dict[str, object]], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.suffix.casefold() == ".json":
        output.write_text(
            json.dumps(rows, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return
    with output.open("w", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export corrected extraction reviews to JSONL or JSON."
    )
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    container = create_container(settings=Settings())
    try:
        rows = build_feedback_rows(
            container.extraction_audit_repository.list_all(),
            container.extraction_review_repository.list_all(),
        )
        write_feedback(rows, args.output)
    finally:
        container.dispose()
    print(f"Exported {len(rows)} corrected reviews to {args.output}")


if __name__ == "__main__":
    main()
