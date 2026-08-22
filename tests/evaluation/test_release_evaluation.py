import json

import httpx

from order_assistant.evaluation.release import (
    analyze_dataset,
    build_release_report,
    write_release_report,
)


def result(dataset: str, run: int, case_id: str = "case", critical: bool = True):
    actual = {
        "model": "6204",
        "quantity": None,
        "primary_brand": None,
        "fallback_brands": [],
        "max_unit_price": None,
        "delivery_deadline": None,
        "allow_split_fulfillment": False,
        "requires_clarification": False,
        "clarification_questions": [],
    }
    return {
        "case_id": case_id,
        "dataset": dataset,
        "tags": ["security", "exact"],
        "critical": critical,
        "run": run,
        "input_text": "SKF 6204",
        "expected": {"model": "6204"},
        "explicit_fields": ["model"],
        "expects_clarification": False,
        "expected_clarification_codes": [],
        "expected_grounding_issue_codes": [],
        "must_not_contain": ["sku-23"],
        "raw_schema_valid": True,
        "raw_actual": dict(actual),
        "guarded_actual": dict(actual),
        "grounding_issues": [],
        "grounding_changed": False,
        "raw_semantic_success": True,
        "guarded_semantic_success": True,
        "latency_seconds": float(run),
        "error_type": None,
    }


def profile() -> dict:
    records = []
    for dataset in ("dev", "holdout"):
        records.extend(result(dataset, run) for run in (1, 2, 3))
    return {
        "profile_id": "v2-think-false",
        "model": "qwen3.5:9b",
        "prompt_version": "v2",
        "think": False,
        "runs": 3,
        "records": records,
    }


def test_release_analysis_has_runs_worst_run_and_tag_metrics() -> None:
    analyzed = analyze_dataset(profile(), "holdout")

    assert len(analyzed["per_run"]) == 3
    assert analyzed["worst_run"]["semantic_success_rate"] == 1
    assert analyzed["worst_run"]["latency_mean"] == 3
    assert analyzed["by_tag"]["security"]["case_runs"] == 3
    assert analyzed["quality_gate"]["passed"] is True


def test_critical_failure_breaks_release_gate() -> None:
    data = profile()
    failed = next(
        item
        for item in data["records"]
        if item["dataset"] == "holdout" and item["run"] == 2
    )
    failed["guarded_actual"]["model"] = None
    failed["guarded_semantic_success"] = False

    analyzed = analyze_dataset(data, "holdout")

    assert analyzed["quality_gate"]["passed"] is False
    assert analyzed["worst_run"]["critical_cases_passed"] is False


def test_security_failure_in_one_run_breaks_release_gate() -> None:
    data = profile()
    unsafe = next(
        item
        for item in data["records"]
        if item["dataset"] == "holdout" and item["run"] == 3
    )
    unsafe["guarded_actual"]["clarification_questions"] = ["SKU-23"]

    analyzed = analyze_dataset(data, "holdout")

    assert analyzed["quality_gate"]["passed"] is False
    assert analyzed["worst_run"]["security_safe_rate"] < 1


def test_dev_metrics_cannot_replace_failed_holdout_metrics() -> None:
    data = profile()
    failed = next(
        item for item in data["records"] if item["dataset"] == "holdout"
    )
    failed["guarded_actual"]["model"] = None
    failed["guarded_semantic_success"] = False

    report = build_release_report(data, "a" * 64)

    assert report["datasets"]["dev"]["quality_gate"]["passed"] is True
    assert report["datasets"]["holdout"]["quality_gate"]["passed"] is False
    assert report["release_quality_gate"]["passed"] is False


def test_release_report_contains_manifest_configuration_and_worst_run(tmp_path) -> None:
    report = build_release_report(profile(), "b" * 64)

    json_path, markdown_path = write_release_report(
        tmp_path / "release.json", report
    )

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    markdown = markdown_path.read_text(encoding="utf-8")
    assert payload["manifest_sha256"] == "b" * 64
    assert payload["configuration"] == {
        "model": "qwen3.5:9b",
        "prompt_version": "v2",
        "think": False,
        "runs": 3,
        "pipeline": "guarded",
    }
    assert "worst_run" in payload["datasets"]["holdout"]
    assert payload["datasets"]["holdout"]["guarded_metrics"]["latency_mean"] == 2
    assert "Worst holdout run" in markdown
    assert "thinking" not in json_path.read_text(encoding="utf-8").lower()


def test_offline_release_analysis_does_not_call_http(monkeypatch) -> None:
    def fail_if_called(*args, **kwargs):
        raise AssertionError("Offline release analysis must not call HTTP.")

    monkeypatch.setattr(httpx.Client, "post", fail_if_called)

    report = build_release_report(profile(), "c" * 64)

    assert report["release_quality_gate"]["passed"] is True
