import hashlib
import json
import re
import unicodedata
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from order_assistant.domain import GroundingIssueCode


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATASET_DIR = PROJECT_ROOT / "evals" / "datasets"
MANIFEST_DIR = PROJECT_ROOT / "evals" / "manifests"
DEV_DATASET_PATH = DATASET_DIR / "rfq_dev_v1.json"
HOLDOUT_DATASET_PATH = DATASET_DIR / "rfq_holdout_v1.json"
HOLDOUT_MANIFEST_PATH = MANIFEST_DIR / "rfq_holdout_v1.sha256"


class DatasetIntegrityError(ValueError):
    """Raised when a frozen evaluation dataset no longer matches its manifest."""


class EvaluationCase(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9_]+$")
    tags: list[str] = Field(min_length=1)
    text: str = Field(min_length=1)
    expected: dict[str, Any]
    explicit_fields: list[str] = Field(default_factory=list)
    expects_clarification: bool = False
    expected_clarification_codes: list[GroundingIssueCode] = Field(
        default_factory=list
    )
    expected_grounding_issue_codes: list[GroundingIssueCode] = Field(
        default_factory=list
    )
    must_not_contain: list[str] = Field(default_factory=list)
    critical: bool = False


def normalize_source_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text).casefold()
    return re.sub(r"\s+", " ", normalized).strip()


def _load_json(path: Path) -> list[dict[str, Any]]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_dataset(name: Literal["dev", "holdout"]) -> list[dict[str, Any]]:
    path = DEV_DATASET_PATH if name == "dev" else HOLDOUT_DATASET_PATH
    raw_cases = _load_json(path)
    cases = []
    for raw in raw_cases:
        if name == "dev":
            raw = {
                **raw,
                "tags": raw.get("tags", [raw.get("category", "dev")]),
                "expected_clarification_codes": raw.get(
                    "expected_clarification_codes", []
                ),
                "expected_grounding_issue_codes": raw.get(
                    "expected_grounding_issue_codes", []
                ),
                "critical": raw.get("critical", raw.get("category") == "security"),
            }
        case = EvaluationCase.model_validate(raw).model_dump(mode="json")
        case["dataset"] = name
        case["category"] = raw.get("category", case["tags"][0])
        cases.append(case)
    ids = [case["id"] for case in cases]
    if len(ids) != len(set(ids)):
        raise ValueError(f"Dataset {name} contains duplicate ids.")
    return cases


def load_datasets(selection: Literal["dev", "holdout", "all"]) -> list[dict[str, Any]]:
    if selection == "dev":
        return load_dataset("dev")
    if selection == "holdout":
        return load_dataset("holdout")
    return load_dataset("dev") + load_dataset("holdout")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(64 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def expected_manifest_hash(manifest_path: Path = HOLDOUT_MANIFEST_PATH) -> str:
    first_line = manifest_path.read_text(encoding="utf-8").splitlines()[0]
    expected = first_line.split()[0].lower()
    if not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise DatasetIntegrityError("Holdout manifest has an invalid SHA-256 value.")
    return expected


def verify_holdout_manifest(
    dataset_path: Path = HOLDOUT_DATASET_PATH,
    manifest_path: Path = HOLDOUT_MANIFEST_PATH,
) -> str:
    expected = expected_manifest_hash(manifest_path)
    actual = sha256_file(dataset_path)
    if actual != expected:
        raise DatasetIntegrityError(
            f"Holdout manifest mismatch: expected {expected}, got {actual}."
        )
    return actual
