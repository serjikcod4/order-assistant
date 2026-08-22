import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi.testclient import TestClient
from pydantic import ValidationError

from order_assistant.api.app import create_app
from order_assistant.api.container import create_container
from order_assistant.config import Settings


ROOT = Path(__file__).parents[1]
STRONG_KEY = "test-only-key-with-at-least-32-characters"


def test_disabled_production_settings_do_not_require_ollama(tmp_path: Path) -> None:
    settings = Settings(
        environment="production",
        persistence_backend="sqlalchemy",
        database_url=f"sqlite:///{tmp_path / 'disabled.db'}",
        extractor_backend="disabled",
        llm_rollout_mode="disabled",
        audit_hmac_key=STRONG_KEY,
    )
    assert settings.extractor_backend == "disabled"
    assert settings.llm_rollout_mode == "disabled"


def test_sqlalchemy_backend_requires_database_url() -> None:
    with pytest.raises(ValidationError, match="database_url"):
        Settings(persistence_backend="sqlalchemy", database_url=None)


@pytest.mark.parametrize("mode", ["shadow", "review"])
def test_active_rollout_requires_ollama_and_real_hmac(mode: str) -> None:
    with pytest.raises(ValidationError, match="extractor_backend=ollama"):
        Settings(
            llm_rollout_mode=mode,
            extractor_backend="disabled",
            audit_hmac_key=STRONG_KEY,
        )
    with pytest.raises(ValidationError, match="real audit HMAC"):
        Settings(
            llm_rollout_mode=mode,
            extractor_backend="ollama",
            audit_hmac_key="development-only-placeholder",
        )


def test_production_rejects_obvious_or_short_hmac_secret() -> None:
    for value in ("replace-with-a-random-secret", "too-short"):
        with pytest.raises(ValidationError, match="Production environment"):
            Settings(environment="production", audit_hmac_key=value)


def test_compose_defaults_are_disabled_and_migration_gates_api() -> None:
    compose = yaml.safe_load((ROOT / "compose.yaml").read_text(encoding="utf-8"))
    services = compose["services"]
    environment = services["api"]["environment"]
    assert environment["ORDER_ASSISTANT_EXTRACTOR_BACKEND"] == "disabled"
    assert environment["ORDER_ASSISTANT_LLM_ROLLOUT_MODE"] == "disabled"
    assert services["migrate"]["command"] == ["alembic", "upgrade", "head"]
    assert services["api"]["depends_on"]["migrate"]["condition"] == (
        "service_completed_successfully"
    )
    assert services["api"]["depends_on"]["postgres"]["condition"] == (
        "service_healthy"
    )
    assert "ollama" not in services


def test_shadow_override_cannot_enable_review_and_targets_host_ollama() -> None:
    override = yaml.safe_load(
        (ROOT / "compose.ollama-shadow.yaml").read_text(encoding="utf-8")
    )
    environment = override["services"]["api"]["environment"]
    assert environment["ORDER_ASSISTANT_LLM_ROLLOUT_MODE"] == "shadow"
    assert environment["ORDER_ASSISTANT_EXTRACTOR_BACKEND"] == "ollama"
    assert environment["ORDER_ASSISTANT_OLLAMA_BASE_URL"] == (
        "http://host.docker.internal:11434"
    )
    assert "review" not in (ROOT / "compose.yaml").read_text(encoding="utf-8")


def test_docker_runtime_is_non_root_and_one_worker() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "USER app" in dockerfile
    assert '"--workers", "1"' in dockerfile
    assert "alembic upgrade" not in dockerfile
    assert ".env" not in dockerfile


def test_health_responses_do_not_expose_database_url_or_hmac(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'private-database-name.db'}"
    container = create_container(
        settings=Settings(
            persistence_backend="sqlalchemy",
            database_url=database_url,
            audit_hmac_key=STRONG_KEY,
        )
    )
    try:
        client = TestClient(create_app(container))
        live = client.get("/health/live")
        ready = client.get("/health/ready")
        combined = live.text + ready.text
        assert live.status_code == 200 and ready.status_code == 200
        assert database_url not in combined
        assert "private-database-name" not in combined
        assert STRONG_KEY not in combined
    finally:
        container.dispose()


def test_alembic_chain_has_one_head_and_expected_lineage() -> None:
    script = ScriptDirectory.from_config(Config(str(ROOT / "alembic.ini")))
    assert script.get_heads() == ["0004_http_erp_metadata"]
    revisions = list(script.walk_revisions(base="base", head="heads"))
    assert [revision.revision for revision in revisions] == [
        "0004_http_erp_metadata",
        "0003_llm_runtime_resilience",
        "0002_extraction_audits",
        "0001_initial",
    ]


def test_runtime_and_dev_dependencies_are_separated_and_constrained() -> None:
    runtime = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    development = (ROOT / "requirements-dev.txt").read_text(encoding="utf-8")
    assert "pytest" not in runtime.casefold()
    assert "psycopg[binary]" in runtime
    assert "pytest==" in development
    assert all(
        "==" in line or ">=" in line
        for line in runtime.splitlines()
        if line and not line.startswith("#")
    )


def test_lesson_20_import_is_silent() -> None:
    result = subprocess.run(
        [sys.executable, "-c", "import lesson_20"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    assert result.stdout == "" and result.stderr == ""


def test_docker_smoke_script_is_ascii_after_optional_bom() -> None:
    script = (ROOT / "scripts/smoke_docker.ps1").read_bytes().decode("utf-8-sig")
    assert script.encode("ascii").decode("ascii") == script
    assert "Need 500 SKF 6204 bearings" in script
    assert '$result.status -ne "shadow_processed"' in script
    assert "$null -ne $result.draft_id" in script


def test_windows_powershell_51_parses_bomless_smoke_script(
    tmp_path: Path,
) -> None:
    powershell = shutil.which("powershell.exe")
    if powershell is None:
        pytest.skip("Windows PowerShell is not available on this platform.")
    source = (ROOT / "scripts/smoke_docker.ps1").read_bytes().decode("utf-8-sig")
    bomless = tmp_path / "smoke_docker_bomless.ps1"
    bomless.write_bytes(source.encode("ascii"))
    escaped_path = str(bomless).replace("'", "''")
    command = (
        "$tokens=$null; $errors=$null; "
        "[System.Management.Automation.Language.Parser]::ParseFile("
        f"'{escaped_path}', [ref]$tokens, [ref]$errors) | Out-Null; "
        "if ($errors.Count -gt 0) { $errors | Out-String | Write-Error; exit 1 }"
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
