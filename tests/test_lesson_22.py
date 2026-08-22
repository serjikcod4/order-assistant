import re
import subprocess
import sys
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

from order_assistant.config import Settings
from scripts.check_markdown_links import broken_links


ROOT = Path(__file__).parents[1]
ADR_NAMES = [
    "001-llm-only-for-extraction.md",
    "002-human-approval.md",
    "003-idempotency-and-reconciliation.md",
    "004-grounding-and-evals.md",
    "005-uow-around-external-calls.md",
    "006-local-ollama.md",
    "007-staged-rollout.md",
]


def test_portfolio_documents_exist() -> None:
    required = [
        ROOT / "AGENTS.md",
        ROOT / "docs/case-study.md",
        ROOT / "docs/threat-model.md",
        ROOT / "docs/demo-script.md",
        ROOT / "docs/interview-defense.md",
        ROOT / "docs/release-readiness.md",
        ROOT / "examples/order-assistant.http",
    ]
    required.extend(ROOT / "docs/adr" / name for name in ADR_NAMES)
    assert all(path.is_file() for path in required)


def test_readme_leads_with_business_ai_boundaries_workflow_and_evidence() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    opening = readme[:7000]
    assert "Portfolio" in opening
    assert "AI **не разрешено**" in opening
    assert "```mermaid" in opening
    assert "Human approval" in opening
    assert "Synthetic holdout" in opening
    assert "Runtime benchmark" in opening
    assert "timeout-after-creation" in opening


def test_all_adrs_have_required_sections() -> None:
    for name in ADR_NAMES:
        content = (ROOT / "docs/adr" / name).read_text(encoding="utf-8")
        for section in (
            "## Context",
            "## Decision",
            "## Consequences",
            "## Alternatives considered",
        ):
            assert section in content, f"{name} lacks {section}"


def test_threat_model_covers_required_threats_and_demo_identity_warning() -> None:
    content = (ROOT / "docs/threat-model.md").read_text(encoding="utf-8")
    required = [
        "Prompt injection",
        "Hallucinated fields",
        "Client-supplied identity",
        "Forged approval",
        "Leaked ERP token",
        "Replayed HTTP create",
        "Idempotency conflict",
        "Malicious ERP response",
        "Oversized ERP response",
        "Timeout uncertainty",
        "DoS",
        "Sensitive source text",
        "Database exposure",
    ]
    assert all(threat in content for threat in required)
    assert "нельзя использовать в production" in content


def test_interview_defense_contains_at_least_25_questions() -> None:
    content = (ROOT / "docs/interview-defense.md").read_text(encoding="utf-8")
    assert len(re.findall(r"(?m)^\d+\. \*\*", content)) >= 25


def test_http_examples_cover_release_scenarios_without_real_tokens() -> None:
    content = (ROOT / "examples/order-assistant.http").read_text(encoding="utf-8")
    for endpoint in (
        "/health/live",
        "/order-requests",
        "/order-requests/from-text",
        "/approve",
        "/submit",
        "/retry",
        "/reconcile",
        "/extraction-audits/summary",
        "/extraction-runtime/summary",
    ):
        assert endpoint in content
    assert not re.search(r"(?:sk-|ghp_)[A-Za-z0-9_-]{16,}", content)


def test_repository_markdown_links_resolve_offline() -> None:
    assert broken_links(ROOT) == []


def test_lesson_22_does_not_change_production_defaults_or_migration_head() -> None:
    settings = Settings()
    assert settings.llm_rollout_mode == "disabled"
    assert settings.erp_backend == "fake"
    script = ScriptDirectory.from_config(Config(str(ROOT / "alembic.ini")))
    assert script.get_heads() == ["0004_http_erp_metadata"]


def test_release_link_checker_runs_as_a_silent_import_and_successful_cli() -> None:
    imported = subprocess.run(
        [sys.executable, "-c", "import scripts.check_markdown_links"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    checked = subprocess.run(
        [sys.executable, "scripts/check_markdown_links.py"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert imported.stdout == "" and imported.stderr == ""
    assert checked.returncode == 0, checked.stdout + checked.stderr
