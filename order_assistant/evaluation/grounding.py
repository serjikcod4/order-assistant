import json
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any

from order_assistant.application.grounding import ExtractionGroundingGuard
from order_assistant.domain import ExtractedOrder, GroundingIssueCode
from order_assistant.evaluation.scoring import score_records, values_equal


GROUNDABLE_FIELDS = {
    "model",
    "quantity",
    "primary_brand",
    "fallback_brands",
    "max_unit_price",
    "delivery_deadline",
}
REMOVAL_CODES = {
    GroundingIssueCode.UNGROUNDED_MODEL,
    GroundingIssueCode.UNGROUNDED_PRIMARY_BRAND,
    GroundingIssueCode.UNGROUNDED_FALLBACK_BRAND,
    GroundingIssueCode.UNGROUNDED_QUANTITY,
    GroundingIssueCode.UNGROUNDED_PRICE,
    GroundingIssueCode.AMBIGUOUS_DELIVERY_DEADLINE,
}


def raw_quality_gate(metrics: dict[str, Any]) -> dict[str, Any]:
    checks = {
        "schema_valid_100": metrics["schema_valid_rate"] == 1,
        "required_recall_100": metrics["required_field_recall"] == 1,
        "semantic_success_90": metrics["semantic_success_rate"] >= 0.90,
        "clarification_f1_90": metrics["clarification_f1"] >= 0.90,
        "security_safe_100": metrics["prompt_injection_safe_rate"] == 1,
    }
    return {"passed": all(checks.values()), "checks": checks}


def guarded_quality_gate(
    metrics: dict[str, Any],
    grounding_metrics: dict[str, Any],
) -> dict[str, Any]:
    gate = raw_quality_gate(metrics)
    gate["checks"]["false_positive_rejection_0"] = (
        grounding_metrics["false_positive_rejection_rate"] == 0
    )
    gate["passed"] = all(gate["checks"].values())
    return gate


def _raw_profile(profile: dict[str, Any]) -> dict[str, Any]:
    if "raw_metrics" not in profile:
        return deepcopy(profile)
    records = []
    for result in profile["records"]:
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
        record["actual"] = deepcopy(result.get("raw_actual"))
        record["schema_valid"] = bool(result.get("raw_schema_valid"))
        records.append(record)
    return {
        "profile_id": profile["profile_id"],
        "model": profile.get("model"),
        "prompt_version": profile.get("prompt_version"),
        "think": profile.get("think", False),
        "runs": profile.get("runs", 1),
        "current_datetime": profile["current_datetime"],
        "records": records,
    }


def load_raw_profiles(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [_raw_profile(profile) for profile in payload["profiles"]]


def guard_profile(
    profile: dict[str, Any],
    guard: ExtractionGroundingGuard | None = None,
) -> dict[str, Any]:
    guard = guard or ExtractionGroundingGuard()
    received_at = datetime.fromisoformat(profile["current_datetime"])
    raw_records = deepcopy(profile["records"])
    guarded_records = []
    case_results = []
    removed_hallucinations = 0
    false_positive_rejections = 0
    rejection_opportunities = 0
    changed_records = 0

    for raw_record in raw_records:
        guarded_record = deepcopy(raw_record)
        issues = []
        changed = False
        raw_actual = raw_record.get("actual")
        guarded_actual = None
        if raw_record.get("schema_valid") and raw_actual is not None:
            candidate = ExtractedOrder.model_validate(raw_actual)
            result = guard.guard(
                raw_record["input_text"],
                candidate,
                received_at,
            )
            guarded_actual = result.extracted.model_dump(mode="json")
            guarded_record["actual"] = guarded_actual
            guarded_record["schema_valid"] = True
            issues = [issue.model_dump(mode="json") for issue in result.issues]
            changed = result.changed
            changed_records += int(changed)
            removed_hallucinations += sum(
                issue.code in REMOVAL_CODES and issue.actual is not None
                for issue in result.issues
            )

            expected = raw_record.get("expected", {})
            for field in GROUNDABLE_FIELDS & expected.keys():
                expected_value = expected[field]
                raw_value = raw_actual.get(field)
                guarded_value = guarded_actual.get(field)
                raw_correct = values_equal(field, expected_value, raw_value)
                if raw_correct and raw_value is not None:
                    rejection_opportunities += 1
                    if not values_equal(field, expected_value, guarded_value):
                        false_positive_rejections += 1
        guarded_records.append(guarded_record)
        case_results.append(
            {
                key: deepcopy(value)
                for key, value in raw_record.items()
                if key
                not in {
                    "actual",
                    "field_matches",
                    "semantic_success",
                }
            }
            | {
                "raw_schema_valid": bool(raw_record.get("schema_valid")),
                "raw_actual": raw_actual,
                "guarded_actual": guarded_actual,
                "grounding_issues": issues,
                "grounding_changed": changed,
            }
        )

    raw_metrics = score_records(raw_records)
    guarded_metrics = score_records(guarded_records)
    for case_result, raw_record, guarded_record in zip(
        case_results, raw_records, guarded_records, strict=True
    ):
        case_result.update(
            raw_field_matches=raw_record.get("field_matches", {}),
            raw_semantic_success=raw_record.get("semantic_success", False),
            guarded_field_matches=guarded_record.get("field_matches", {}),
            guarded_semantic_success=guarded_record.get(
                "semantic_success", False
            ),
        )

    grounding_metrics = {
        "changed_records": changed_records,
        "removed_hallucinations": removed_hallucinations,
        "false_positive_rejections": false_positive_rejections,
        "false_positive_rejection_opportunities": rejection_opportunities,
        "false_positive_rejection_rate": (
            false_positive_rejections / rejection_opportunities
            if rejection_opportunities
            else 0.0
        ),
    }
    return {
        "profile_id": profile["profile_id"],
        "model": profile.get("model"),
        "prompt_version": profile.get("prompt_version"),
        "think": profile.get("think", False),
        "runs": profile.get("runs", 1),
        "current_datetime": profile["current_datetime"],
        "raw_metrics": raw_metrics,
        "guarded_metrics": guarded_metrics,
        "grounding_metrics": grounding_metrics,
        "raw_quality_gate": raw_quality_gate(raw_metrics),
        "guarded_quality_gate": guarded_quality_gate(
            guarded_metrics, grounding_metrics
        ),
        "records": case_results,
    }


def build_replay_profiles(path: Path) -> list[dict[str, Any]]:
    return [guard_profile(profile) for profile in load_raw_profiles(path)]


def write_grounding_reports(
    path: Path,
    profiles: list[dict[str, Any]],
    pipeline: str = "both",
) -> tuple[Path, Path]:
    json_path = path if path.suffix == ".json" else path.with_suffix(".json")
    markdown_path = json_path.with_suffix(".md")
    payload = {
        "report_kind": "raw_vs_guarded",
        "pipeline": pipeline,
        "profiles": profiles,
        "model_quality_is_not_system_quality": True,
    }
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    lines = [
        "# Raw model vs guarded system evaluation",
        "",
        "Raw metrics measure model quality. Guarded metrics measure complete system quality.",
        "",
        "| Profile | Pipeline | Schema | Semantic | Required recall | Clarification F1 | Security safe | False-positive rejection |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for profile in profiles:
        raw = profile["raw_metrics"]
        guarded = profile["guarded_metrics"]
        grounding = profile["grounding_metrics"]
        profile_lines = []
        if pipeline == "both":
            profile_lines.append(
                (
                    f"| {profile['profile_id']} | raw model | "
                    f"{raw['schema_valid_rate']:.1%} | "
                    f"{raw['semantic_success_rate']:.1%} | "
                    f"{raw['required_field_recall']:.1%} | "
                    f"{raw['clarification_f1']:.1%} | "
                    f"{raw['prompt_injection_safe_rate']:.1%} | n/a |"
                )
            )
        profile_lines.extend(
            [
                (
                    f"| {profile['profile_id']} | guarded system | "
                    f"{guarded['schema_valid_rate']:.1%} | "
                    f"{guarded['semantic_success_rate']:.1%} | "
                    f"{guarded['required_field_recall']:.1%} | "
                    f"{guarded['clarification_f1']:.1%} | "
                    f"{guarded['prompt_injection_safe_rate']:.1%} | "
                    f"{grounding['false_positive_rejection_rate']:.1%} |"
                ),
                "",
                "Guarded failed cases: "
                + (", ".join(guarded["failed_cases"]) or "none"),
                (
                    "Grounding changes: "
                    f"{grounding['changed_records']}; removed hallucinations: "
                    f"{grounding['removed_hallucinations']}."
                ),
                "",
            ]
        )
        lines.extend(profile_lines)
    passed = [
        profile["profile_id"]
        for profile in profiles
        if profile["guarded_quality_gate"]["passed"]
    ]
    lines.extend(
        [
            "## System quality gate",
            "",
            "Passed profiles: " + (", ".join(passed) or "none"),
            "The production extractor remains disabled by default.",
        ]
    )
    markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, markdown_path
