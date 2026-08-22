import json

import pytest

from order_assistant.domain import ExtractedOrder
from order_assistant.evaluation.datasets import (
    DatasetIntegrityError,
    HOLDOUT_DATASET_PATH,
    HOLDOUT_MANIFEST_PATH,
    load_dataset,
    normalize_source_text,
    verify_holdout_manifest,
)


def test_dev_and_holdout_datasets_are_valid_and_versioned() -> None:
    dev = load_dataset("dev")
    holdout = load_dataset("holdout")

    assert len(dev) == 22
    assert len(holdout) >= 36
    for case in holdout:
        ExtractedOrder.model_validate(case["expected"])
        assert case["tags"]
        assert isinstance(case["critical"], bool)


def test_ids_are_unique_within_and_between_datasets() -> None:
    cases = load_dataset("dev") + load_dataset("holdout")
    ids = [case["id"] for case in cases]

    assert len(ids) == len(set(ids))


def test_normalized_texts_do_not_overlap_between_dev_and_holdout() -> None:
    dev_texts = {
        normalize_source_text(case["text"]) for case in load_dataset("dev")
    }
    holdout_texts = {
        normalize_source_text(case["text"]) for case in load_dataset("holdout")
    }

    assert dev_texts.isdisjoint(holdout_texts)
    assert len(holdout_texts) == len(load_dataset("holdout"))


def test_security_and_safety_holdout_cases_are_critical() -> None:
    cases = load_dataset("holdout")
    protected = [
        case
        for case in cases
        if {"security", "safety"}.intersection(case["tags"])
    ]

    assert protected
    assert all(case["critical"] for case in protected)


def test_holdout_manifest_matches_frozen_dataset() -> None:
    manifest_hash = verify_holdout_manifest()

    assert len(manifest_hash) == 64
    assert manifest_hash in HOLDOUT_MANIFEST_PATH.read_text(encoding="utf-8")


def test_tampered_holdout_is_detected(tmp_path) -> None:
    tampered = tmp_path / "rfq_holdout_v1.json"
    data = json.loads(HOLDOUT_DATASET_PATH.read_text(encoding="utf-8"))
    data[0]["text"] += " altered"
    tampered.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(DatasetIntegrityError, match="manifest mismatch"):
        verify_holdout_manifest(tampered, HOLDOUT_MANIFEST_PATH)
