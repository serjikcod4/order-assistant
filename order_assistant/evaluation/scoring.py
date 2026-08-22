import json
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from enum import Enum
from pathlib import Path
from typing import Any


DECIMAL_FIELDS = {"max_unit_price"}
DATETIME_FIELDS = {"delivery_deadline"}
UNORDERED_LIST_FIELDS = {"fallback_brands"}
REQUIRED_FIELDS = {"model", "quantity", "primary_brand", "max_unit_price", "delivery_deadline"}


def _datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        result = value
    elif isinstance(value, str):
        try:
            result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if result.tzinfo is None:
        result = result.replace(tzinfo=timezone.utc)
    return result.astimezone(timezone.utc)


def _plain(value: Any) -> Any:
    return value.value if isinstance(value, Enum) else value


def values_equal(field: str, expected: Any, actual: Any) -> bool:
    expected, actual = _plain(expected), _plain(actual)
    if expected is None or actual is None:
        return expected is actual
    if field in DECIMAL_FIELDS:
        try:
            return Decimal(str(expected)) == Decimal(str(actual))
        except InvalidOperation:
            return False
    if field in DATETIME_FIELDS:
        return _datetime(expected) == _datetime(actual)
    if field in UNORDERED_LIST_FIELDS:
        return {_plain(item) for item in expected} == {_plain(item) for item in actual}
    return expected == actual


def _percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def score_records(records: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(records)
    valid = [record for record in records if record.get("schema_valid")]
    field_totals: dict[str, int] = {}
    field_hits: dict[str, int] = {}
    semantic_hits = required_total = required_hits = 0
    tp = fp = fn = 0
    failed_cases = []

    for record in records:
        expected = record.get("expected", {})
        actual = record.get("actual") or {}
        matches = {}
        for field, expected_value in expected.items():
            if field == "requires_clarification":
                continue
            field_totals[field] = field_totals.get(field, 0) + 1
            match = bool(record.get("schema_valid")) and values_equal(
                field, expected_value, actual.get(field)
            )
            matches[field] = match
            field_hits[field] = field_hits.get(field, 0) + int(match)
        explicit_required = set(record.get("explicit_fields") or ()) & REQUIRED_FIELDS
        if not explicit_required:
            explicit_required = {
                field
                for field, value in expected.items()
                if field in REQUIRED_FIELDS and value is not None
            }
        for field in explicit_required:
            required_total += 1
            required_hits += int(matches.get(field, False))
        semantic_success = bool(record.get("schema_valid")) and all(matches.values())
        semantic_hits += int(semantic_success)
        expected_clarification = bool(record.get("expects_clarification", expected.get("requires_clarification", False)))
        actual_clarification = bool(actual.get("requires_clarification", False)) if record.get("schema_valid") else False
        tp += int(expected_clarification and actual_clarification)
        fp += int(not expected_clarification and actual_clarification)
        fn += int(expected_clarification and not actual_clarification)
        record["field_matches"] = matches
        record["semantic_success"] = semantic_success
        case_id = record.get("case_id")
        if not semantic_success and case_id not in failed_cases:
            failed_cases.append(case_id)

    precision = tp / (tp + fp) if tp + fp else 1.0
    recall = tp / (tp + fn) if tp + fn else 1.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    groups: dict[str, list[str]] = {}
    for record in records:
        signature = (
            json.dumps(record["actual"], sort_keys=True, ensure_ascii=False)
            if record.get("schema_valid")
            else f"error:{record.get('error_type')}"
        )
        groups.setdefault(record["case_id"], []).append(
            signature
        )
    stability = (
        sum(len(set(outputs)) == 1 for outputs in groups.values()) / len(groups)
        if groups else 0.0
    )
    latencies = [float(record["latency_seconds"]) for record in records]
    security_records = [record for record in records if record.get("must_not_contain")]
    safe_security = sum(
        record.get("schema_valid")
        and all(
            term.lower()
            not in json.dumps(
                record.get("actual") or {}, ensure_ascii=False
            ).lower()
            for term in record["must_not_contain"]
        )
        for record in security_records
    )
    compared_fields = sum(field_totals.values())
    return {
        "schema_valid_rate": len(valid) / total if total else 0.0,
        "semantic_success_rate": semantic_hits / total if total else 0.0,
        "field_accuracy": sum(field_hits.values()) / compared_fields if compared_fields else 0.0,
        "field_accuracy_by_field": {
            field: field_hits.get(field, 0) / count for field, count in field_totals.items()
        },
        "required_field_recall": required_hits / required_total if required_total else 1.0,
        "clarification_precision": precision,
        "clarification_recall": recall,
        "clarification_f1": f1,
        "latency_p50": _percentile(latencies, 0.50),
        "latency_p95": _percentile(latencies, 0.95),
        "stability": stability,
        "invalid_json_count": sum(record.get("error_type") == "invalid_json" for record in records),
        "schema_invalid_count": sum(record.get("error_type") == "schema_invalid" for record in records),
        "prompt_injection_safe_rate": (
            safe_security / len(security_records) if security_records else 1.0
        ),
        "failed_cases": failed_cases,
    }


def write_reports(path: Path, profiles: list[dict[str, Any]]) -> tuple[Path, Path]:
    json_path = path if path.suffix == ".json" else path.with_suffix(".json")
    markdown_path = json_path.with_suffix(".md")
    ranked = sorted(
        profiles,
        key=lambda item: (
            item["metrics"]["semantic_success_rate"],
            item["metrics"]["required_field_recall"],
            -item["metrics"]["latency_p95"],
        ),
        reverse=True,
    )
    recommended = ranked[0] if ranked else None
    gate_passed = bool(
        recommended and recommended.get("quality_gate", {}).get("passed", False)
    )
    recommendation = {
        "profile_id": recommended["profile_id"] if recommended else None,
        "quality_gate_passed": gate_passed,
        "enable_production_backend": gate_passed,
    }
    payload = {"profiles": profiles, "recommendation": recommendation}
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        "# Ollama extractor evaluation",
        "",
        "| Profile | Runs | Schema valid | Semantic success | Field accuracy | Required recall | Clarification F1 | Security safe | Invalid JSON | Schema invalid | p50 | p95 | Stability |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for profile in profiles:
        metrics = profile["metrics"]
        lines.append(
            f"| {profile['profile_id']} | {profile.get('runs', 1)} | "
            f"{metrics['schema_valid_rate']:.1%} | "
            f"{metrics['semantic_success_rate']:.1%} | "
            f"{metrics['field_accuracy']:.1%} | "
            f"{metrics['required_field_recall']:.1%} | "
            f"{metrics['clarification_f1']:.1%} | "
            f"{metrics['prompt_injection_safe_rate']:.1%} | "
            f"{metrics['invalid_json_count']} | "
            f"{metrics['schema_invalid_count']} | "
            f"{metrics['latency_p50']:.2f}s | "
            f"{metrics['latency_p95']:.2f}s | {metrics['stability']:.1%} |"
        )
        lines.extend(["", f"Failed cases: {', '.join(metrics['failed_cases']) or 'none'}"])
    if recommended:
        gate_label = "PASSED" if gate_passed else "FAILED"
        lines.extend(
            [
                "",
                "## Recommendation",
                "",
                f"Best measured profile: `{recommended['profile_id']}`.",
                f"Quality gate: **{gate_label}**.",
                (
                    "The production extractor may be enabled."
                    if gate_passed
                    else "Keep the production extractor disabled by default."
                ),
            ]
        )
    markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, markdown_path
