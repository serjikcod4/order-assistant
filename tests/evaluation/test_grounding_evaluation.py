import json

import httpx

from order_assistant.evaluation.grounding import (
    build_replay_profiles,
    guard_profile,
    write_grounding_reports,
)


def raw_profile() -> dict:
    return {
        "profile_id": "v2-think-false",
        "model": "test-model",
        "prompt_version": "v2",
        "think": False,
        "runs": 1,
        "current_datetime": "2026-08-14T12:00:00+00:00",
        "records": [
            {
                "case_id": "hallucinated",
                "category": "missing",
                "run": 1,
                "input_text": "Нужны подшипники.",
                "expected": {"model": None},
                "explicit_fields": [],
                "expects_clarification": True,
                "must_not_contain": ["sku-23"],
                "schema_valid": True,
                "actual": {
                    "model": "6204",
                    "quantity": None,
                    "primary_brand": None,
                    "fallback_brands": [],
                    "max_unit_price": None,
                    "delivery_deadline": None,
                    "allow_split_fulfillment": False,
                    "requires_clarification": False,
                    "clarification_questions": ["Уточните SKU-23"],
                },
                "error_type": None,
                "latency_seconds": 1.0,
            },
            {
                "case_id": "grounded",
                "category": "model",
                "run": 1,
                "input_text": "Нужна модель 6204.",
                "expected": {"model": "6204"},
                "explicit_fields": ["model"],
                "expects_clarification": True,
                "must_not_contain": [],
                "schema_valid": True,
                "actual": {
                    "model": "6204",
                    "quantity": None,
                    "primary_brand": None,
                    "fallback_brands": [],
                    "max_unit_price": None,
                    "delivery_deadline": None,
                    "allow_split_fulfillment": False,
                    "requires_clarification": False,
                    "clarification_questions": [],
                },
                "error_type": None,
                "latency_seconds": 1.0,
            },
        ],
    }


def test_raw_and_guarded_metrics_are_separate() -> None:
    compared = guard_profile(raw_profile())

    assert compared["raw_metrics"]["semantic_success_rate"] == 0.5
    assert compared["guarded_metrics"]["semantic_success_rate"] == 1
    assert compared["raw_metrics"]["clarification_f1"] == 0
    assert compared["guarded_metrics"]["clarification_f1"] == 1
    assert compared["guarded_metrics"]["prompt_injection_safe_rate"] == 1
    assert compared["grounding_metrics"]["removed_hallucinations"] == 1
    assert compared["grounding_metrics"]["false_positive_rejection_rate"] == 0


def test_replay_never_calls_ollama(tmp_path, monkeypatch) -> None:
    source = tmp_path / "raw.json"
    source.write_text(
        json.dumps({"profiles": [raw_profile()]}, ensure_ascii=False),
        encoding="utf-8",
    )

    def fail_if_called(*args, **kwargs):
        raise AssertionError("Replay must not perform HTTP requests.")

    monkeypatch.setattr(httpx.Client, "post", fail_if_called)

    profiles = build_replay_profiles(source)

    assert len(profiles) == 1
    assert profiles[0]["guarded_metrics"]["semantic_success_rate"] == 1


def test_raw_vs_guarded_json_and_markdown_report(tmp_path) -> None:
    profile = guard_profile(raw_profile())

    json_path, markdown_path = write_grounding_reports(
        tmp_path / "grounded.json",
        [profile],
    )

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    markdown = markdown_path.read_text(encoding="utf-8")
    assert payload["model_quality_is_not_system_quality"] is True
    assert "raw model" in markdown
    assert "guarded system" in markdown
    assert "thinking" not in json_path.read_text(encoding="utf-8").lower()
