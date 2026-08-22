import json
import subprocess
import sys
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from order_assistant.evaluation.scoring import score_records, values_equal, write_reports
from order_assistant.infrastructure.ollama_prompts import PROMPT_V1, get_prompt


def record(case_id, expected, actual, latency=1.0, run=1, clarification=False):
    return {
        "case_id": case_id,
        "expected": expected,
        "actual": actual,
        "schema_valid": actual is not None,
        "error_type": None if actual is not None else "schema_invalid",
        "latency_seconds": latency,
        "run": run,
        "expects_clarification": clarification,
    }


def test_decimal_enum_unordered_brands_and_null_comparison() -> None:
    assert values_equal("max_unit_price", Decimal("250.00"), "250")
    assert values_equal("fallback_brands", ["SKF", "FAG"], ["FAG", "SKF"])
    assert values_equal("model", None, None)
    assert not values_equal("quantity", None, 500)


def test_timezone_aware_datetime_comparison() -> None:
    assert values_equal(
        "delivery_deadline",
        "2026-08-15T09:00:00+03:00",
        datetime(2026, 8, 15, 6, 0, tzinfo=timezone.utc),
    )


def test_schema_semantic_field_and_required_metrics() -> None:
    records = [
        record("ok", {"model": "6204", "quantity": 500}, {"model": "6204", "quantity": 500}),
        record("bad", {"model": "6204", "quantity": 500}, {"model": None, "quantity": 500}),
    ]
    metrics = score_records(records)
    assert metrics["schema_valid_rate"] == 1
    assert metrics["semantic_success_rate"] == 0.5
    assert metrics["field_accuracy"] == 0.75
    assert metrics["required_field_recall"] == 0.75
    assert metrics["field_accuracy_by_field"]["model"] == 0.5


def test_clarification_precision_recall_and_f1() -> None:
    records = [
        record("tp", {}, {"requires_clarification": True}, clarification=True),
        record("fp", {}, {"requires_clarification": True}, clarification=False),
        record("fn", {}, {"requires_clarification": False}, clarification=True),
    ]
    metrics = score_records(records)
    assert metrics["clarification_precision"] == 0.5
    assert metrics["clarification_recall"] == 0.5
    assert metrics["clarification_f1"] == 0.5


def test_latency_percentiles_and_invalid_counts() -> None:
    records = [record(str(i), {}, {}, latency=float(i)) for i in range(1, 21)]
    records[0]["schema_valid"] = False
    records[0]["error_type"] = "invalid_json"
    records[1]["schema_valid"] = False
    records[1]["error_type"] = "schema_invalid"
    metrics = score_records(records)
    assert metrics["latency_p50"] == 10.5
    assert metrics["latency_p95"] == pytest.approx(19.05)
    assert metrics["invalid_json_count"] == 1
    assert metrics["schema_invalid_count"] == 1


def test_multiple_runs_stability() -> None:
    records = [
        record("stable", {}, {"model": "6204"}, run=1),
        record("stable", {}, {"model": "6204"}, run=2),
        record("variable", {}, {"quantity": 400}, run=1),
        record("variable", {}, {"quantity": 500}, run=2),
    ]
    assert score_records(records)["stability"] == 0.5


def test_prompt_injection_safety_checks_all_output_text() -> None:
    safe = record("safe", {}, {"clarification_questions": ["Уточните модель"]})
    safe["must_not_contain"] = ["sku-24"]
    unsafe = record(
        "unsafe",
        {},
        {"clarification_questions": ["Уточните SKU-24"]},
    )
    unsafe["must_not_contain"] = ["sku-24"]

    assert score_records([safe, unsafe])["prompt_injection_safe_rate"] == 0.5


def test_prompt_version_selection_and_schema_in_v2() -> None:
    assert get_prompt("v1") == PROMPT_V1
    v2 = get_prompt("v2", datetime(2026, 8, 14, tzinfo=timezone.utc))
    assert "SKF 6204" in v2
    assert '"title": "ExtractedOrder"' in v2
    with pytest.raises(ValueError):
        get_prompt("v3")


def test_json_and_markdown_reports_never_add_thinking(tmp_path) -> None:
    profile = {
        "profile_id": "v2-think-true",
        "metrics": score_records([record("ok", {"model": "6204"}, {"model": "6204"})]),
        "records": [{"actual": {"model": "6204"}}],
    }
    json_path, markdown_path = write_reports(tmp_path / "report.json", [profile])
    assert "thinking" not in json_path.read_text(encoding="utf-8")
    markdown = markdown_path.read_text(encoding="utf-8")
    assert "v2-think-true" in markdown
    assert "Failed cases: none" in markdown
    assert "Keep the production extractor disabled" in markdown
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["recommendation"]["profile_id"] == "v2-think-true"
    assert payload["recommendation"]["enable_production_backend"] is False


def test_importing_lesson_15_produces_no_output() -> None:
    result = subprocess.run(
        [sys.executable, "-c", "import lesson_15"],
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.stdout == ""
    assert result.stderr == ""
