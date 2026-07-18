#!/usr/bin/env python3
"""Ship-it helpers: run tests and scan for accidental secrets before commit/push."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

# High-confidence secret patterns (real credentials, not placeholders).
SECRET_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("dotenv_file", re.compile(r"(^|/)\.env$")),
    (
        "valyu_key",
        re.compile(r"\bval_[0-9a-f]{40,}\b", re.IGNORECASE),
    ),
    (
        "openai_or_sk",
        re.compile(r"\bsk-(?:cp|or|proj|live|test)?-[A-Za-z0-9_-]{16,}\b"),
    ),
    (
        "sk_generic",
        re.compile(r"\bsk-[A-Za-z0-9]{20,}\b"),
    ),
    (
        "bearer_token",
        re.compile(r"\bBearer\s+[A-Za-z0-9._\-]{20,}\b"),
    ),
    (
        "api_key_assignment",
        re.compile(
            r"""(?i)\b(?:api[_-]?key|secret|token|password)\b\s*[=:]\s*['\"]?(?!your-)[A-Za-z0-9_\-]{20,}"""
        ),
    ),
]

# Lines that intentionally document forbidden patterns.
ALLOWLIST_LINE_RES: list[re.Pattern[str]] = [
    re.compile(r"#\s*❌\s*BAD"),
    re.compile(r"(?i)\b(?:placeholder|example|your-.*-here|redact)\b"),
    re.compile(r"val_real-key-here"),
    re.compile(r"val_[0-9a-f]*\.\.\."),
    re.compile(r"sk-\.\.\."),
]

NEVER_STAGE_NAMES = {".env"}
NEVER_STAGE_SUFFIXES = (".pem", ".key")


@dataclass(frozen=True)
class Finding:
    path: str
    line_no: int
    kind: str
    excerpt: str


def find_repo_root(start: Optional[Path] = None) -> Path:
    """Walk parents until a .git directory is found; else cwd."""
    current = (start or Path.cwd()).resolve()
    for parent in [current, *current.parents]:
        if (parent / ".git").exists():
            return parent
    return current


def is_allowlisted_line(line: str) -> bool:
    return any(p.search(line) for p in ALLOWLIST_LINE_RES)


def path_is_forbidden(path: str | Path) -> bool:
    name = Path(path).name
    if name in NEVER_STAGE_NAMES:
        return True
    return name.endswith(NEVER_STAGE_SUFFIXES)


def scan_text(text: str, path: str = "<memory>") -> list[Finding]:
    """Scan text for secret-like content; skip allowlisted documentation lines.

    A line is skipped when it matches an allowlist pattern, or when the previous
    non-empty line is an explicit `# ❌ BAD` documentation marker.
    """
    findings: list[Finding] = []
    if path_is_forbidden(path):
        findings.append(
            Finding(path=path, line_no=0, kind="forbidden_path", excerpt=Path(path).name)
        )
        return findings

    lines = text.splitlines()
    prev_nonempty = ""
    for line_no, line in enumerate(lines, start=1):
        skip = is_allowlisted_line(line) or bool(
            re.search(r"#\s*❌\s*BAD", prev_nonempty)
        )
        if not skip:
            for kind, pattern in SECRET_PATTERNS:
                if kind == "dotenv_file":
                    continue
                if pattern.search(line):
                    excerpt = line.strip()
                    if len(excerpt) > 120:
                        excerpt = excerpt[:117] + "..."
                    findings.append(
                        Finding(path=path, line_no=line_no, kind=kind, excerpt=excerpt)
                    )
                    break
        if line.strip():
            prev_nonempty = line
    return findings


def scan_paths(paths: Iterable[Path]) -> list[Finding]:
    findings: list[Finding] = []
    for path in paths:
        rel = str(path)
        if path_is_forbidden(path):
            findings.append(
                Finding(path=rel, line_no=0, kind="forbidden_path", excerpt=path.name)
            )
            continue
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        findings.extend(scan_text(text, path=rel))
    return findings


def git_changed_files(repo_root: Path, staged_only: bool = False) -> list[Path]:
    """Return changed file paths relative to repo root."""
    cmds: list[list[str]] = []
    if staged_only:
        cmds.append(["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"])
    else:
        cmds.append(["git", "diff", "--name-only", "--diff-filter=ACMR"])
        cmds.append(["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"])
        cmds.append(["git", "ls-files", "--others", "--exclude-standard"])

    names: set[str] = set()
    for cmd in cmds:
        result = subprocess.run(
            cmd,
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            continue
        for line in result.stdout.splitlines():
            line = line.strip()
            if line:
                names.add(line)
    return [repo_root / name for name in sorted(names)]


def detect_test_command(repo_root: Path) -> list[str]:
    """Prefer pytest when a tests/ tree or pytest config exists."""
    has_tests = (repo_root / "tests").is_dir()
    has_pytest_cfg = any(
        (repo_root / name).exists()
        for name in ("pytest.ini", "pyproject.toml", "setup.cfg", "tox.ini")
    )
    if has_tests or has_pytest_cfg:
        return [sys.executable, "-m", "pytest", "-q"]
    package_json = repo_root / "package.json"
    if package_json.exists():
        return ["npm", "test"]
    return [sys.executable, "-m", "pytest", "-q"]


def run_tests(repo_root: Path, extra_args: Optional[list[str]] = None) -> int:
    cmd = detect_test_command(repo_root)
    if extra_args:
        cmd = [*cmd, *extra_args]
    print(f"Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=repo_root, check=False)
    return result.returncode


def format_findings(findings: list[Finding]) -> str:
    if not findings:
        return "No secret findings."
    lines = [f"Found {len(findings)} potential secret(s):"]
    for f in findings:
        loc = f"{f.path}:{f.line_no}" if f.line_no else f.path
        lines.append(f"  - [{f.kind}] {loc}: {f.excerpt}")
    return "\n".join(lines)


def cmd_test(repo_root: Path, pytest_args: list[str]) -> int:
    return run_tests(repo_root, extra_args=pytest_args or None)


def cmd_scan(repo_root: Path, staged_only: bool) -> int:
    paths = git_changed_files(repo_root, staged_only=staged_only)
    if not paths:
        print("No changed files to scan.")
        return 0
    findings = scan_paths(paths)
    print(format_findings(findings))
    return 1 if findings else 0


def cmd_check(repo_root: Path, staged_only: bool, pytest_args: list[str]) -> int:
    scan_code = cmd_scan(repo_root, staged_only=staged_only)
    if scan_code != 0:
        print("Secret scan failed; aborting before tests.")
        return scan_code
    test_code = run_tests(repo_root, extra_args=pytest_args or None)
    if test_code != 0:
        print("Tests failed; do not commit or push.")
        return test_code
    print("Ship check passed: secrets clean and tests green.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Ship-it gate: secret scan and test runner for this workspace."
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=None,
        help="Repository root (default: discover from cwd)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_test = sub.add_parser("test", help="Run the project test suite")
    p_test.add_argument("pytest_args", nargs="*", help="Extra args forwarded to pytest")

    p_scan = sub.add_parser("scan", help="Scan changed files for secrets")
    p_scan.add_argument(
        "--staged",
        action="store_true",
        help="Scan only staged files",
    )

    p_check = sub.add_parser("check", help="Scan secrets then run tests (ship gate)")
    p_check.add_argument("--staged", action="store_true", help="Scan only staged files")
    p_check.add_argument("pytest_args", nargs="*", help="Extra args forwarded to pytest")

    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    repo_root = find_repo_root(args.repo_root)

    if args.command == "test":
        return cmd_test(repo_root, args.pytest_args)
    if args.command == "scan":
        return cmd_scan(repo_root, staged_only=args.staged)
    if args.command == "check":
        return cmd_check(repo_root, staged_only=args.staged, pytest_args=args.pytest_args)
    parser.error(f"Unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
