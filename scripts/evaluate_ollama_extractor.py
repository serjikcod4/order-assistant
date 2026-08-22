import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from order_assistant.domain import LLMInvalidOutputError  # noqa: E402
from order_assistant.evaluation.datasets import (  # noqa: E402
    DatasetIntegrityError,
    load_datasets,
    verify_holdout_manifest,
)
from order_assistant.evaluation.grounding import (  # noqa: E402
    build_replay_profiles,
    guard_profile,
    raw_quality_gate,
    write_grounding_reports,
)
from order_assistant.evaluation.scoring import (  # noqa: E402
    score_records,
    write_reports,
)
from order_assistant.evaluation.release import (  # noqa: E402
    build_release_report,
    write_release_report,
)
from order_assistant.infrastructure.extractors import (  # noqa: E402
    OllamaOrderExtractor,
)


def parse_bool(value: str) -> bool:
    lowered = value.lower()
    if lowered not in {"true", "false"}:
        raise argparse.ArgumentTypeError("Expected true or false.")
    return lowered == "true"


def evaluate_live(args: argparse.Namespace) -> dict:
    cases = load_datasets(args.dataset)
    current = datetime(2026, 8, 14, 12, 0, tzinfo=timezone.utc)
    extractor = OllamaOrderExtractor(
        "http://localhost:11434",
        args.model,
        120,
        prompt_version=args.prompt_version,
        think=args.think,
        current_datetime=current,
    )
    records = []
    try:
        for run in range(1, args.runs + 1):
            for case in cases:
                started = perf_counter()
                record = {
                    "case_id": case["id"],
                    "category": case["category"],
                    "dataset": case["dataset"],
                    "tags": case.get("tags", []),
                    "critical": case.get("critical", False),
                    "run": run,
                    "input_text": case["text"],
                    "expected": case["expected"],
                    "explicit_fields": case.get("explicit_fields", []),
                    "expects_clarification": case.get(
                        "expects_clarification", False
                    ),
                    "must_not_contain": case.get("must_not_contain", []),
                    "expected_clarification_codes": case.get(
                        "expected_clarification_codes", []
                    ),
                    "expected_grounding_issue_codes": case.get(
                        "expected_grounding_issue_codes", []
                    ),
                }
                try:
                    actual = extractor.extract(case["text"])
                    record.update(
                        schema_valid=True,
                        actual=actual.model_dump(mode="json"),
                        error_type=None,
                    )
                except LLMInvalidOutputError as error:
                    cause = error.__cause__
                    errors = cause.errors() if hasattr(cause, "errors") else []
                    kind = (
                        "invalid_json"
                        if errors and errors[0].get("type") == "json_invalid"
                        else "schema_invalid"
                    )
                    record.update(
                        schema_valid=False,
                        actual=None,
                        error_type=kind,
                        error_message=str(error),
                    )
                except Exception as error:
                    record.update(
                        schema_valid=False,
                        actual=None,
                        error_type="request_error",
                        error_message=type(error).__name__,
                    )
                record["latency_seconds"] = perf_counter() - started
                records.append(record)
                print(
                    f"{args.prompt_version}/think={args.think} run={run} "
                    f"{case['id']}: {record['error_type'] or 'valid'}"
                )
    finally:
        extractor.close()
    metrics = score_records(records)
    return {
        "profile_id": f"{args.prompt_version}-think-{str(args.think).lower()}",
        "model": args.model,
        "prompt_version": args.prompt_version,
        "think": args.think,
        "runs": args.runs,
        "current_datetime": current.isoformat(),
        "metrics": metrics,
        "quality_gate": raw_quality_gate(metrics),
        "records": records,
    }


def _write_raw(path: Path, profiles: list[dict]) -> tuple[Path, Path]:
    raw_profiles = []
    for profile in profiles:
        records = []
        for result in profile["records"]:
            record = {
                key: value
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
            record["actual"] = result.get("raw_actual")
            record["schema_valid"] = result.get("raw_schema_valid", False)
            records.append(record)
        raw_profiles.append(
            {
                "profile_id": profile["profile_id"],
                "model": profile.get("model"),
                "prompt_version": profile.get("prompt_version"),
                "think": profile.get("think", False),
                "runs": profile.get("runs", 1),
                "current_datetime": profile["current_datetime"],
                "metrics": profile["raw_metrics"],
                "quality_gate": profile["raw_quality_gate"],
                "records": records,
            }
        )
    return write_reports(path, raw_profiles)


def run(args: argparse.Namespace) -> tuple[Path, Path, list[dict]]:
    if args.replay:
        compared_profiles = build_replay_profiles(args.replay)
        if args.prompt_version:
            compared_profiles = [
                profile
                for profile in compared_profiles
                if profile.get("prompt_version") == args.prompt_version
                and profile.get("think") == args.think
            ]
    else:
        compared_profiles = [guard_profile(evaluate_live(args))]

    if not compared_profiles:
        raise ValueError("No profiles matched the requested replay filters.")
    if args.release:
        manifest_hash = verify_holdout_manifest()
        report = build_release_report(compared_profiles[0], manifest_hash)
        json_path, markdown_path = write_release_report(args.output, report)
        compared_profiles[0]["release_quality_gate"] = report[
            "release_quality_gate"
        ]
    elif args.pipeline == "raw":
        json_path, markdown_path = _write_raw(args.output, compared_profiles)
    else:
        json_path, markdown_path = write_grounding_reports(
            args.output,
            compared_profiles,
            pipeline=args.pipeline,
        )
    return json_path, markdown_path, compared_profiles


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prompt-version", choices=["v1", "v2"])
    parser.add_argument("--think", type=parse_bool, default=False)
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--model", default="qwen3.5:9b")
    parser.add_argument(
        "--dataset",
        choices=["dev", "holdout", "all"],
        default="dev",
    )
    parser.add_argument(
        "--pipeline",
        choices=["raw", "guarded", "both"],
        default="both",
    )
    parser.add_argument("--replay", type=Path)
    parser.add_argument("--release", action="store_true")
    parser.add_argument("--verify-manifest", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.runs < 1:
        parser.error("--runs must be at least 1")
    if not args.replay and not args.prompt_version:
        parser.error("--prompt-version is required for a live eval")
    if args.release:
        release_errors = []
        if args.replay:
            release_errors.append("--release cannot use --replay")
        if args.dataset != "all":
            release_errors.append("--release requires --dataset all")
        if args.prompt_version != "v2":
            release_errors.append("--release requires --prompt-version v2")
        if args.think:
            release_errors.append("--release requires --think false")
        if args.runs < 3:
            release_errors.append("--release requires at least 3 runs")
        if args.model != "qwen3.5:9b":
            release_errors.append("--release requires local qwen3.5:9b")
        if args.pipeline == "raw":
            release_errors.append("--release requires a guarded pipeline")
        if release_errors:
            parser.error("; ".join(release_errors))
    try:
        if args.verify_manifest or args.release:
            manifest_hash = verify_holdout_manifest()
            print(f"Holdout manifest verified: {manifest_hash}")
    except DatasetIntegrityError as error:
        parser.error(str(error))
    try:
        json_path, markdown_path, profiles = run(args)
    except ValueError as error:
        parser.error(str(error))
    print(f"JSON report: {json_path}")
    print(f"Markdown report: {markdown_path}")
    for profile in profiles:
        if args.release:
            print(
                "Holdout release quality gate: "
                f"{profile['release_quality_gate']['passed']}"
            )
        else:
            print(
                f"{profile['profile_id']} guarded quality gate: "
                f"{profile['guarded_quality_gate']['passed']}"
            )


if __name__ == "__main__":
    main()
