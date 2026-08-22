"""Validate repository-local Markdown links without network access."""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import unquote


ROOT = Path(__file__).resolve().parents[1]
LINK_PATTERN = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
EXTERNAL_PREFIXES = ("http://", "https://", "mailto:", "#")


def markdown_files(root: Path = ROOT) -> list[Path]:
    files = [root / "README.md", root / "AGENTS.md"]
    files.extend(sorted((root / "docs").rglob("*.md")))
    return [path for path in files if path.exists()]


def broken_links(root: Path = ROOT) -> list[str]:
    failures: list[str] = []
    for markdown in markdown_files(root):
        content = markdown.read_text(encoding="utf-8")
        for raw_target in LINK_PATTERN.findall(content):
            target = raw_target.strip().strip("<>")
            if target.startswith(EXTERNAL_PREFIXES):
                continue
            path_part = unquote(target.split("#", 1)[0])
            if not path_part:
                continue
            resolved = (markdown.parent / path_part).resolve()
            if not resolved.exists():
                relative = markdown.relative_to(root)
                failures.append(f"{relative}: {target}")
    return failures


def main() -> int:
    failures = broken_links()
    if failures:
        for failure in failures:
            print(failure)
        return 1
    print(f"Markdown links OK: {len(markdown_files())} files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
