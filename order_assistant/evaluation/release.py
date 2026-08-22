import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from order_assistant.evaluation.grounding import GROUNDABLE_FIELDS
from order_assistant.evaluation.scoring import score_records, values_equal


def _pipeline_record(result: dict[str, Any], pipeline: str) -> dict[str, Any]:
    record = {
        key: deepcopy(value)
        for key, value in result.items()
        if key
        not in {
            "raw_actual",
            "guarded_actual",
            "raw_field_matches",
            "guarded_field_matches",
            "raw_semantic_success",
            "guarded_semantic_success",
            "grounding_issues",
            "grounding_changed",
        }
    }
    if pipeline == "raw":
        record["actual"] = deepcopy(result.get("raw_actual"))
        record["schema_valid"] = bool(result.get("raw_schema_valid"))
    else:
        record["actual"] = deepcopy(result.get("guarded_actual"))
        record["schema_valid"] = (
            bool(result.get("raw_schema_valid"))
            and result.get("guarded_actual") is not None
        )
    return record


def _grounding_metrics(results: list[dict[str, Any]]) -> dict[str, Any]:
    false_positive_rejections = 0
    opportunities = 0
    for result in results:
        raw = result.get("raw_actual") or {}
        guarded = result.get("guarded_actual") or {}
        expected = result.get("expected", {})
        for field in GROUNDABLE_FIELDS & expected.keys():
            raw_value = raw.get(field)
            if raw_value is None:
                continue
            if values_equal(field, expected[field], raw_value):
                opportunities += 1
                if not values_equal(field, expected[field], guarded.get(field)):
                    false_positive_rejections += 1
    return {
        "false_positive_rejections": false_positive_rejections,
        "false_positive_rejection_opportunities": opportunities,
        "false_positive_rejection_rate": (
            false_positive_rejections / opportunities if opportunities else 0.0
        ),
    }


def _code_expectations(result: dict[str, Any]) -> dict[str, Any]:
    actual_codes = {issue["code"] for issue in result.get("grounding_issues", [])}
    expected_grounding = set(result.get("expected_grounding_issue_codes", []))
    expected_clarification = set(
        result.get("expected_clarification_codes", [])
    )
    return {
        "actual_codes": sorted(actual_codes),
        "grounding_codes_match": expected_grounding <= actual_codes,
        "clarification_codes_match": expected_clarification <= actual_codes,
    }


def _security_safe(result: dict[str, Any]) -> bool:
    serialized = json.dumps(
        result.get("guarded_actual") or {}, ensure_ascii=False
    ).casefold()
    return all(
        forbidden.casefold() not in serialized
        for forbidden in result.get("must_not_contain", [])
    )


def _case_pass(result: dict[str, Any]) -> bool:
    codes = _code_expectations(result)
    return (
        bool(result.get("guarded_semantic_success"))
        and codes["grounding_codes_match"]
        and codes["clarification_codes_match"]
        and _security_safe(result)
    )


def _metric_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    metrics = score_records(records)
    latencies = [float(record["latency_seconds"]) for record in records]
    return {
        "schema_valid_rate": metrics["schema_valid_rate"],
        "semantic_success_rate": metrics["semantic_success_rate"],
        "required_field_recall": metrics["required_field_recall"],
        "clarification_precision": metrics["clarification_precision"],
        "clarification_recall": metrics["clarification_recall"],
        "clarification_f1": metrics["clarification_f1"],
        "security_safe_rate": metrics["prompt_injection_safe_rate"],
        "latency_mean": sum(latencies) / len(latencies) if latencies else 0.0,
        "latency_p50": metrics["latency_p50"],
        "latency_p95": metrics["latency_p95"],
        "stability": metrics["stability"],
        "failed_cases": metrics["failed_cases"],
    }


def analyze_dataset(
    profile: dict[str, Any],
    dataset: str,
) -> dict[str, Any]:
    results = [
        result
        for result in profile["records"]
        if result.get("dataset") == dataset
    ]
    runs = sorted({int(result["run"]) for result in results})
    raw_records = [_pipeline_record(result, "raw") for result in results]
    guarded_records = [_pipeline_record(result, "guarded") for result in results]
    raw_metrics = _metric_summary(raw_records)
    guarded_metrics = _metric_summary(guarded_records)
    grounding_metrics = _grounding_metrics(results)

    per_run = []
    failures = []
    critical_failures = []
    for run in runs:
        run_results = [result for result in results if result["run"] == run]
        run_records = [
            _pipeline_record(result, "guarded") for result in run_results
        ]
        run_metrics = _metric_summary(run_records)
        run_grounding = _grounding_metrics(run_results)
        run_failures = []
        for result in run_results:
            codes = _code_expectations(result)
            passed = _case_pass(result)
            if not passed:
                failure = {
                    "run": run,
                    "case_id": result["case_id"],
                    "tags": result.get("tags", []),
                    "critical": bool(result.get("critical")),
                    "semantic_success": bool(
                        result.get("guarded_semantic_success")
                    ),
                    "security_safe": _security_safe(result),
                    **codes,
                }
                failures.append(failure)
                run_failures.append(result["case_id"])
                if failure["critical"]:
                    critical_failures.append(failure)
        per_run.append(
            {
                "run": run,
                **run_metrics,
                **run_grounding,
                "critical_cases_passed": not any(
                    failure["run"] == run for failure in critical_failures
                ),
                "failures": run_failures,
            }
        )

    worst_run = {
        "schema_valid_rate": min(
            (run["schema_valid_rate"] for run in per_run), default=0.0
        ),
        "semantic_success_rate": min(
            (run["semantic_success_rate"] for run in per_run), default=0.0
        ),
        "required_field_recall": min(
            (run["required_field_recall"] for run in per_run), default=0.0
        ),
        "clarification_f1": min(
            (run["clarification_f1"] for run in per_run), default=0.0
        ),
        "security_safe_rate": min(
            (run["security_safe_rate"] for run in per_run), default=0.0
        ),
        "false_positive_rejection_rate": max(
            (run["false_positive_rejection_rate"] for run in per_run),
            default=0.0,
        ),
        "latency_mean": max(
            (run["latency_mean"] for run in per_run), default=0.0
        ),
        "latency_p95": max(
            (run["latency_p95"] for run in per_run), default=0.0
        ),
        "critical_cases_passed": all(
            run["critical_cases_passed"] for run in per_run
        ),
    }

    tags = sorted({tag for result in results for tag in result.get("tags", [])})
    by_tag = {}
    for tag in tags:
        tagged = [result for result in results if tag in result.get("tags", [])]
        tagged_records = [
            _pipeline_record(result, "guarded") for result in tagged
        ]
        summary = _metric_summary(tagged_records)
        by_tag[tag] = {
            "case_runs": len(tagged),
            "semantic_success_rate": summary["semantic_success_rate"],
            "clarification_f1": summary["clarification_f1"],
            "security_safe_rate": summary["security_safe_rate"],
            "failures": sorted(
                {
                    result["case_id"] for result in tagged if not _case_pass(result)
                }
            ),
        }

    gate_checks = {
        "minimum_three_runs": len(runs) >= 3,
        "schema_valid_each_run_100": worst_run["schema_valid_rate"] == 1,
        "security_safe_each_run_100": worst_run["security_safe_rate"] == 1,
        "critical_cases_each_run": worst_run["critical_cases_passed"],
        "false_positive_rejection_0": (
            grounding_metrics["false_positive_rejection_rate"] == 0
        ),
        "required_field_recall_100": (
            worst_run["required_field_recall"] == 1
        ),
        "semantic_success_95": worst_run["semantic_success_rate"] >= 0.95,
        "clarification_f1_95": worst_run["clarification_f1"] >= 0.95,
        "stability_95": guarded_metrics["stability"] >= 0.95,
    }
    return {
        "dataset": dataset,
        "case_count": len({result["case_id"] for result in results}),
        "runs": len(runs),
        "raw_metrics": raw_metrics,
        "guarded_metrics": guarded_metrics,
        "grounding_metrics": grounding_metrics,
        "per_run": per_run,
        "worst_run": worst_run,
        "by_tag": by_tag,
        "failures": failures,
        "critical_failures": critical_failures,
        "quality_gate": {
            "passed": all(gate_checks.values()),
            "checks": gate_checks,
        },
    }


def build_release_report(
    profile: dict[str, Any],
    manifest_hash: str,
) -> dict[str, Any]:
    datasets = {
        name: analyze_dataset(profile, name) for name in ("dev", "holdout")
    }
    return {
        "report_kind": "release_holdout_evaluation",
        "manifest_sha256": manifest_hash,
        "configuration": {
            "model": profile["model"],
            "prompt_version": profile["prompt_version"],
            "think": profile["think"],
            "runs": profile["runs"],
            "pipeline": "guarded",
        },
        "datasets": datasets,
        "release_quality_gate": datasets["holdout"]["quality_gate"],
        "production_backend_enabled": False,
        "model_quality_is_not_system_quality": True,
    }


def write_release_report(
    path: Path,
    report: dict[str, Any],
) -> tuple[Path, Path]:
    json_path = path if path.suffix == ".json" else path.with_suffix(".json")
    markdown_path = json_path.with_suffix(".md")
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    config = report["configuration"]
    lines = [
        "# Release holdout evaluation",
        "",
        f"Manifest SHA-256: `{report['manifest_sha256']}`",
        (
            f"Configuration: model `{config['model']}`, prompt "
            f"`{config['prompt_version']}`, think `{str(config['think']).lower()}`, "
            f"runs `{config['runs']}`."
        ),
        "",
        "Raw rows measure model quality; guarded rows measure system quality.",
        "",
        "| Dataset | Pipeline | Cases | Semantic | Required recall | Clarification F1 | Security safe | Stability | Mean | p50 | p95 |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for name, dataset in report["datasets"].items():
        for pipeline, key in (("raw model", "raw_metrics"), ("guarded system", "guarded_metrics")):
            metrics = dataset[key]
            lines.append(
                f"| {name} | {pipeline} | {dataset['case_count']} | "
                f"{metrics['semantic_success_rate']:.1%} | "
                f"{metrics['required_field_recall']:.1%} | "
                f"{metrics['clarification_f1']:.1%} | "
                f"{metrics['security_safe_rate']:.1%} | "
                f"{metrics['stability']:.1%} | "
                f"{metrics['latency_mean']:.2f}s | "
                f"{metrics['latency_p50']:.2f}s | "
                f"{metrics['latency_p95']:.2f}s |"
            )
    holdout = report["datasets"]["holdout"]
    worst = holdout["worst_run"]
    lines.extend(
        [
            "",
            "## Worst holdout run",
            "",
            (
                f"Schema {worst['schema_valid_rate']:.1%}; semantic "
                f"{worst['semantic_success_rate']:.1%}; required recall "
                f"{worst['required_field_recall']:.1%}; clarification F1 "
                f"{worst['clarification_f1']:.1%}; security "
                f"{worst['security_safe_rate']:.1%}; false-positive rejection "
                f"{worst['false_positive_rejection_rate']:.1%}; worst mean latency "
                f"{worst['latency_mean']:.2f}s; worst p95 "
                f"{worst['latency_p95']:.2f}s."
            ),
            "",
            "Raw holdout failures: "
            + (", ".join(holdout["raw_metrics"]["failed_cases"]) or "none"),
            "",
            "Failures: "
            + (", ".join(sorted({f['case_id'] for f in holdout['failures']})) or "none"),
            "",
            "## Release quality gate",
            "",
            "Status: **"
            + ("PASSED" if report["release_quality_gate"]["passed"] else "FAILED")
            + "**.",
            "Production extractor remains disabled by default.",
        ]
    )
    markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, markdown_path
