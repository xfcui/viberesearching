"""Tests for the ship-it secret scan and test detection helpers."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

SCRIPT = (
    Path(__file__).resolve().parents[1]
    / ".cursor"
    / "skills"
    / "ship-it"
    / "scripts"
    / "ship_it.py"
)


def load_ship_it():
    spec = importlib.util.spec_from_file_location("ship_it", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["ship_it"] = module
    spec.loader.exec_module(module)
    return module


ship_it = load_ship_it()


class TestAllowlistAndForbidden:
    def test_allowlisted_bad_example_line(self):
        assert ship_it.is_allowlisted_line("# ❌ BAD — any tracked file")
        assert ship_it.is_allowlisted_line("api_key = your-valyu-api-key-here")
        assert ship_it.is_allowlisted_line('client = Valyu(api_key="val_real-key-here")')

    def test_path_is_forbidden_env(self):
        assert ship_it.path_is_forbidden(".env")
        assert ship_it.path_is_forbidden("subdir/.env")
        assert ship_it.path_is_forbidden("id_rsa.pem")
        assert not ship_it.path_is_forbidden(".env.example")
        assert not ship_it.path_is_forbidden("README.md")


class TestScanText:
    def test_detects_valyu_key(self):
        key = "val_" + ("a" * 48)
        findings = ship_it.scan_text(f"api_key = {key}\n", path="cfg.ini")
        assert any(f.kind == "valyu_key" for f in findings)

    def test_detects_sk_style_key(self):
        fake = "sk-" + ("ab" * 16)
        findings = ship_it.scan_text(f'token = "{fake}"\n', path="app.py")
        assert findings
        assert findings[0].kind in {"sk_generic", "openai_or_sk", "api_key_assignment"}

    def test_ignores_placeholders(self):
        text = textwrap.dedent(
            """
            MINIMAX_API_KEY=your-minimax-api-key-here
            api_key = your-valyu-api-key-here
            """
        )
        assert ship_it.scan_text(text, path=".env.example") == []

    def test_allowlists_documented_bad_example_block(self):
        fake = "val_" + ("9" * 48)
        text = f"# ❌ BAD — any tracked file\napi_key = {fake}\n"
        assert ship_it.scan_text(text, path="docs.md") == []

    def test_flags_key_without_bad_marker_context(self):
        text = "api_key = val_" + ("d" * 48) + "\n"
        findings = ship_it.scan_text(text, path="docs.md")
        assert any(f.kind == "valyu_key" for f in findings)

    def test_same_line_bad_marker_allowlisted(self):
        fake = "val_" + ("8" * 48)
        line = f"# ❌ BAD api_key = {fake}"
        assert ship_it.scan_text(line + "\n", path="rule.mdc") == []

    def test_forbidden_env_path(self):
        findings = ship_it.scan_text("MINIMAX_API_KEY=x\n", path=".env")
        assert len(findings) == 1
        assert findings[0].kind == "forbidden_path"


class TestScanPaths:
    def test_scans_files_on_disk(self, tmp_path: Path):
        good = tmp_path / "ok.py"
        bad = tmp_path / "leak.py"
        good.write_text("print('hi')\n", encoding="utf-8")
        bad.write_text("key = val_" + ("b" * 48) + "\n", encoding="utf-8")
        findings = ship_it.scan_paths([good, bad])
        assert len(findings) == 1
        assert findings[0].path.endswith("leak.py")

    def test_skips_binaryish_unreadable(self, tmp_path: Path):
        blob = tmp_path / "bin.dat"
        blob.write_bytes(b"\xff\xfe\x00\x01")
        assert ship_it.scan_paths([blob]) == []


class TestDetectTestCommand:
    def test_prefers_pytest_when_tests_dir(self, tmp_path: Path):
        (tmp_path / "tests").mkdir()
        cmd = ship_it.detect_test_command(tmp_path)
        assert cmd[-2:] == ["pytest", "-q"] or cmd[-1] == "-q"
        assert "pytest" in cmd

    def test_npm_when_package_json_only(self, tmp_path: Path):
        (tmp_path / "package.json").write_text("{}", encoding="utf-8")
        assert ship_it.detect_test_command(tmp_path) == ["npm", "test"]


class TestFindRepoRoot:
    def test_finds_git_root(self, tmp_path: Path):
        (tmp_path / ".git").mkdir()
        nested = tmp_path / "a" / "b"
        nested.mkdir(parents=True)
        assert ship_it.find_repo_root(nested) == tmp_path.resolve()


class TestFormatFindings:
    def test_empty(self):
        assert "No secret" in ship_it.format_findings([])

    def test_nonempty(self):
        f = ship_it.Finding("a.py", 3, "valyu_key", "val_abc")
        out = ship_it.format_findings([f])
        assert "valyu_key" in out
        assert "a.py:3" in out


class TestCli:
    def test_test_command_runs_pytest(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        (tmp_path / "tests").mkdir()
        calls: list[list[str]] = []

        def fake_run(cmd, cwd=None, check=False, **kwargs):
            calls.append(list(cmd))
            return subprocess.CompletedProcess(cmd, 0)

        monkeypatch.setattr(ship_it.subprocess, "run", fake_run)
        code = ship_it.main(["--repo-root", str(tmp_path), "test"])
        assert code == 0
        assert calls
        assert "pytest" in calls[0]

    def test_scan_clean_tree(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        (tmp_path / ".git").mkdir()
        clean = tmp_path / "clean.py"
        clean.write_text("x = 1\n", encoding="utf-8")

        def fake_changed(repo_root, staged_only=False):
            return [clean]

        monkeypatch.setattr(ship_it, "git_changed_files", fake_changed)
        code = ship_it.main(["--repo-root", str(tmp_path), "scan"])
        assert code == 0

    def test_check_aborts_on_secrets(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        (tmp_path / ".git").mkdir()
        leak = tmp_path / "leak.py"
        leak.write_text("k = val_" + ("c" * 48) + "\n", encoding="utf-8")
        monkeypatch.setattr(ship_it, "git_changed_files", lambda *a, **k: [leak])

        ran_tests = {"yes": False}

        def boom(*a, **k):
            ran_tests["yes"] = True
            return 0

        monkeypatch.setattr(ship_it, "run_tests", boom)
        code = ship_it.main(["--repo-root", str(tmp_path), "check"])
        assert code == 1
        assert ran_tests["yes"] is False

    def test_check_runs_tests_when_clean(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        (tmp_path / ".git").mkdir()
        clean = tmp_path / "ok.py"
        clean.write_text("x = 1\n", encoding="utf-8")
        monkeypatch.setattr(ship_it, "git_changed_files", lambda *a, **k: [clean])
        monkeypatch.setattr(ship_it, "run_tests", lambda *a, **k: 0)
        code = ship_it.main(["--repo-root", str(tmp_path), "check"])
        assert code == 0
