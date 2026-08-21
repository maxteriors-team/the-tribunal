#!/usr/bin/env python3
"""Validate the durable SaaS handoff audit and compliance-register linkage."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / "docs/saas-subscription-handoff-audit-2026-08-19.md"
REGISTER = ROOT / "COMPLIANCE.md"

REQUIRED_SECTIONS = (
    "## Executive decision",
    "## Ranked findings",
    "## Mandatory compliance coverage ledger",
    "## Verification performed",
    "## Not verified",
    "## Needs a lawyer or accountant",
)
REQUIRED_COMMANDS = (
    "make audit.security",
    "make ci.backend",
    "make ci.frontend",
    "make audit.handoff",
)
EVIDENCE_LABEL_RE = re.compile(r"\*\*(RUNTIME|CODE|DEDUCED):\*\*")
FINDING_ID_RE = re.compile(r"^[A-Z][A-Z0-9-]+$")
INLINE_CODE_RE = re.compile(r"`([^`]+)`")


def section(text: str, heading: str, next_heading: str) -> str:
    try:
        return text.split(heading, 1)[1].split(next_heading, 1)[0]
    except IndexError as exc:
        raise AssertionError(f"Could not isolate section {heading!r}") from exc


def table_cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def assert_tables_are_rectangular(path: Path, text: str) -> None:
    expected_pipes: int | None = None
    for line_number, line in enumerate(text.splitlines(), 1):
        if line.startswith("|"):
            pipe_count = line.count("|")
            if expected_pipes is None:
                expected_pipes = pipe_count
            assert pipe_count == expected_pipes, (
                f"{path.relative_to(ROOT)}:{line_number}: Markdown table has {pipe_count} pipes; "
                f"expected {expected_pipes}"
            )
        else:
            expected_pipes = None


def referenced_repo_paths(text: str) -> set[Path]:
    paths: set[Path] = set()
    for token in INLINE_CODE_RE.findall(text):
        candidate = token.split(":", 1)[0]
        if not candidate.startswith((".github/", "backend/", "frontend/", "docs/", "scripts/")):
            continue
        if any(character in candidate for character in "* $"):
            continue
        paths.add(ROOT / candidate)
    return paths


def validate() -> tuple[int, int, int]:
    assert REPORT.is_file(), f"Missing report: {REPORT.relative_to(ROOT)}"
    assert REGISTER.is_file(), f"Missing register: {REGISTER.relative_to(ROOT)}"

    report = REPORT.read_text(encoding="utf-8")
    register = REGISTER.read_text(encoding="utf-8")

    assert "NOT LEGAL ADVICE" in report, "Report must retain its legal-advice disclaimer"
    for heading in REQUIRED_SECTIONS:
        assert heading in report, f"Missing required report section: {heading}"
    for command in REQUIRED_COMMANDS:
        assert f"`{command}`" in report, f"Verification table must name `{command}`"

    for path, text in ((REPORT, report), (REGISTER, register)):
        trailing = [
            number for number, line in enumerate(text.splitlines(), 1) if line.rstrip() != line
        ]
        assert not trailing, f"{path.relative_to(ROOT)} has trailing whitespace on lines {trailing}"
        assert_tables_are_rectangular(path, text)

    findings_block = section(
        report,
        "## Ranked findings",
        "## Mandatory compliance coverage ledger",
    )
    finding_rows = [
        table_cells(line)
        for line in findings_block.splitlines()
        if line.startswith("| ") and not line.startswith(("| ID", "|---"))
    ]
    assert finding_rows, "Ranked findings table is empty"

    finding_ids: set[str] = set()
    for cells in finding_rows:
        assert len(cells) == 6, f"Finding row must have 6 columns: {cells}"
        finding_id, _severity, evidence, *_rest = cells
        assert FINDING_ID_RE.fullmatch(finding_id), f"Invalid finding ID: {finding_id}"
        assert finding_id not in finding_ids, f"Duplicate finding ID: {finding_id}"
        finding_ids.add(finding_id)
        labels = EVIDENCE_LABEL_RE.findall(evidence)
        assert len(labels) == 1, (
            f"{finding_id} must have exactly one evidence label "
            f"(CODE/RUNTIME/DEDUCED); found {labels}"
        )

    ledger_block = section(
        report,
        "## Mandatory compliance coverage ledger",
        "## Product and operational observations",
    )
    fail_rows = [line for line in ledger_block.splitlines() if "| fail |" in line]
    assert fail_rows, "Coverage ledger contains no fail rows"
    unmapped = [
        line
        for line in fail_rows
        if not any(f"`{finding_id}`" in line for finding_id in finding_ids)
    ]
    assert not unmapped, f"Ledger fail rows without ranked finding IDs: {unmapped}"

    missing_paths = [
        path.relative_to(ROOT).as_posix()
        for path in sorted(referenced_repo_paths(report))
        if not path.exists()
    ]
    assert not missing_paths, f"Report references missing repository paths: {missing_paths}"

    report_relative = REPORT.relative_to(ROOT).as_posix()
    assert report_relative in register, "COMPLIANCE.md does not link the handoff audit"
    for finding_id in ("PAY-US-001", "BILL-001", "COST-001", "AI-VENDOR-001"):
        assert finding_id in register, f"COMPLIANCE.md is missing key finding {finding_id}"

    return len(finding_ids), len(fail_rows), len(referenced_repo_paths(report))


def main() -> None:
    finding_count, fail_count, path_count = validate()
    print(
        "✓ SaaS handoff audit structure valid: "
        f"{finding_count} findings, {fail_count} mapped fail rows, {path_count} repository paths"
    )


if __name__ == "__main__":
    main()
