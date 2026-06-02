#!/usr/bin/env python3
"""Verify committed env templates match configuration and env usage."""

from __future__ import annotations

import ast
import re
import sys
from dataclasses import dataclass
from pathlib import Path

# This file lives at ``scripts/dev/check_env_drift.py``; the repo root is two
# directories up.
REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_CONFIG_PATH = REPO_ROOT / "backend" / "app" / "core" / "config.py"
BACKEND_ENV_EXAMPLE_PATH = REPO_ROOT / "backend" / ".env.example"
FRONTEND_ENV_EXAMPLE_PATH = REPO_ROOT / "frontend" / ".env.example"
FRONTEND_SCAN_ROOT = REPO_ROOT / "frontend"

DOTENV_KEY_RE = re.compile(r"^\s*(?:export\s+)?(?P<key>[A-Za-z_][A-Za-z0-9_]*)\s*=")
PROCESS_ENV_DOT_RE = re.compile(r"\bprocess\.env\.([A-Za-z_][A-Za-z0-9_]*)\b")
PROCESS_ENV_BRACKET_RE = re.compile(r"\bprocess\.env\[\s*['\"]([A-Za-z_][A-Za-z0-9_]*)['\"]\s*\]")

FRONTEND_EXTENSIONS = {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"}
FRONTEND_SKIP_DIRS = {
    ".next",
    ".turbo",
    "coverage",
    "node_modules",
    "out",
    "playwright-report",
    "test-results",
}
FRONTEND_MANAGED_ENV_VARS = {
    # Supplied by Next.js, Node.js, or the hosting/CI platform, not by local .env files.
    "CI",
    "NEXT_RUNTIME",
    "NODE_ENV",
    "VERCEL_ENV",
}


@dataclass(frozen=True)
class DriftReport:
    """A single env drift finding."""

    title: str
    missing: tuple[str, ...]
    extra: tuple[str, ...]

    @property
    def has_drift(self) -> bool:
        """Return whether this report contains any drift."""
        return bool(self.missing or self.extra)


def parse_dotenv_keys(path: Path) -> set[str]:
    """Return variable names declared in a dotenv-style template file."""
    if not path.exists():
        return set()

    keys: set[str] = set()
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        match = DOTENV_KEY_RE.match(line)
        if match is None:
            continue
        key = match.group("key")
        if key in keys:
            raise ValueError(
                f"{path.relative_to(REPO_ROOT)}:{line_number}: duplicate env var {key}"
            )
        keys.add(key)
    return keys


def backend_settings_env_vars(path: Path) -> set[str]:
    """Extract Settings fields from backend/app/core/config.py as env var names."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "Settings":
            return {
                statement.target.id.upper()
                for statement in node.body
                if isinstance(statement, ast.AnnAssign)
                and isinstance(statement.target, ast.Name)
                and statement.target.id != "model_config"
            }
    raise ValueError(f"Settings class not found in {path.relative_to(REPO_ROOT)}")


def frontend_env_usage(root: Path) -> set[str]:
    """Scan frontend source/config files for direct process.env usage."""
    used: set[str] = set()
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix not in FRONTEND_EXTENSIONS:
            continue
        if any(part in FRONTEND_SKIP_DIRS for part in path.relative_to(root).parts):
            continue

        text = path.read_text(encoding="utf-8")
        used.update(PROCESS_ENV_DOT_RE.findall(text))
        used.update(PROCESS_ENV_BRACKET_RE.findall(text))
    return used


def compare(title: str, expected: set[str], documented: set[str]) -> DriftReport:
    """Compare expected env vars to documented/template env vars."""
    return DriftReport(
        title=title,
        missing=tuple(sorted(expected - documented)),
        extra=tuple(sorted(documented - expected)),
    )


def print_report(report: DriftReport) -> None:
    """Print a deterministic human-readable report."""
    if not report.has_drift:
        print(f"✓ {report.title}")
        return

    print(f"✗ {report.title}")
    if report.missing:
        print("  Missing from template:")
        for key in report.missing:
            print(f"    - {key}")
    if report.extra:
        print("  Present in template but not used/configured:")
        for key in report.extra:
            print(f"    - {key}")


def main() -> int:
    """Run env drift checks."""
    backend_report = compare(
        "backend/.env.example matches backend/app/core/config.py Settings",
        backend_settings_env_vars(BACKEND_CONFIG_PATH),
        parse_dotenv_keys(BACKEND_ENV_EXAMPLE_PATH),
    )

    frontend_report = compare(
        "frontend/.env.example matches frontend process.env usage",
        frontend_env_usage(FRONTEND_SCAN_ROOT) - FRONTEND_MANAGED_ENV_VARS,
        parse_dotenv_keys(FRONTEND_ENV_EXAMPLE_PATH),
    )

    reports = (backend_report, frontend_report)
    for report in reports:
        print_report(report)

    if any(report.has_drift for report in reports):
        print(
            "\nEnv template drift detected. Update backend/.env.example or "
            "frontend/.env.example, then rerun `make ci.env`."
        )
        return 1

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ValueError as exc:
        print(f"✗ {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
