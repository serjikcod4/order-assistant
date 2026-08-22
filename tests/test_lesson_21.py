import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from alembic.config import Config
from alembic.script import ScriptDirectory
from pydantic import ValidationError

from order_assistant.config import Settings


ROOT = Path(__file__).parents[1]


def test_erp_settings_default_to_fake_without_http_configuration() -> None:
    settings = Settings()
    assert settings.erp_backend == "fake"
    assert settings.extractor_backend == "disabled"
    assert settings.llm_rollout_mode == "disabled"


def test_http_settings_require_token_and_safe_transport() -> None:
    with pytest.raises(ValidationError, match="erp_token"):
        Settings(erp_backend="http", erp_base_url="https://erp.example")
    with pytest.raises(ValidationError, match="Plain HTTP"):
        Settings(
            erp_backend="http",
            erp_base_url="http://erp.example",
            erp_token="secret",
            erp_allow_insecure_http=True,
        )
    settings = Settings(
        erp_backend="http",
        erp_base_url="http://erp-stub:8080",
        erp_token="secret",
        erp_allow_insecure_http=True,
    )
    assert settings.erp_token.get_secret_value() == "secret"


def test_contract_and_compose_override_are_separate_and_safe() -> None:
    contract = yaml.safe_load(
        (ROOT / "docs/contracts/erp-v1.openapi.yaml").read_text(encoding="utf-8")
    )
    assert "/api/v1/orders" in contract["paths"]
    assert "/api/v1/orders/by-idempotency-key/{key}" in contract["paths"]
    override = yaml.safe_load(
        (ROOT / "compose.erp-stub.yaml").read_text(encoding="utf-8")
    )
    api = override["services"]["api"]
    assert api["environment"]["ORDER_ASSISTANT_ERP_BACKEND"] == "http"
    assert api["environment"]["ORDER_ASSISTANT_EXTRACTOR_BACKEND"] == "disabled"
    assert api["depends_on"]["erp-stub"]["condition"] == "service_healthy"
    base = yaml.safe_load((ROOT / "compose.yaml").read_text(encoding="utf-8"))
    assert "erp-stub" not in base["services"]


def test_migration_chain_has_one_0004_head() -> None:
    script = ScriptDirectory.from_config(Config(str(ROOT / "alembic.ini")))
    assert script.get_heads() == ["0004_http_erp_metadata"]
    revisions = [
        revision.revision
        for revision in script.walk_revisions(base="base", head="heads")
    ]
    assert revisions[:2] == [
        "0004_http_erp_metadata",
        "0003_llm_runtime_resilience",
    ]


def test_lesson_21_import_is_silent() -> None:
    result = subprocess.run(
        [sys.executable, "-c", "import lesson_21"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    assert result.stdout == "" and result.stderr == ""


def test_http_erp_smoke_is_ascii_only() -> None:
    source = (ROOT / "scripts/smoke_http_erp.ps1").read_text(encoding="utf-8")
    assert source.encode("ascii").decode("ascii") == source
    assert "actual_creation_count -ne 1" in source
    assert "TIMEOUT_AFTER_CREATION" in source
    assert "compose down" in source
    assert "--volumes" not in source


def test_windows_powershell_51_parses_http_erp_smoke(tmp_path: Path) -> None:
    powershell = shutil.which("powershell.exe")
    if powershell is None:
        pytest.skip("Windows PowerShell 5.1 is unavailable.")
    source = (ROOT / "scripts/smoke_http_erp.ps1").read_text(encoding="utf-8")
    script = tmp_path / "smoke_http_erp.ps1"
    script.write_bytes(source.encode("ascii"))
    escaped = str(script).replace("'", "''")
    command = (
        "$tokens=$null; $errors=$null; "
        "[System.Management.Automation.Language.Parser]::ParseFile("
        f"'{escaped}', [ref]$tokens, [ref]$errors) | Out-Null; "
        "if ($errors.Count -gt 0) { exit 1 }"
    )
    result = subprocess.run(
        [
            powershell,
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            command,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
