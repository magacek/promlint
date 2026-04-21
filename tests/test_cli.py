"""End-to-end CLI tests via subprocess.

These run `promlint` as a real executable (installed via `pip install -e .`)
against the fixture files, asserting exit codes and output shape. They're the
strongest signal that the whole thing actually works when a user runs it.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).parent / "fixtures"


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "promlint.cli", *args],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )


def test_good_fixture_exits_zero():
    result = _run(str(FIXTURES / "good_rules.yml"))
    assert result.returncode == 0, result.stdout + result.stderr
    assert "no findings" in result.stdout.lower()


def test_bad_fixture_exits_nonzero_and_shows_findings():
    result = _run(str(FIXTURES / "bad_rules.yml"))
    assert result.returncode == 1, result.stdout + result.stderr
    # Every check should appear in the output
    for check_id in [
        "missing-for",
        "missing-annotations",
        "missing-severity-label",
        "short-rate-window",
        "counter-without-rate",
        "aggregation-drops-identifying-labels",
        "duplicate-alert-expression",
    ]:
        assert f"[{check_id}]" in result.stdout, check_id


def test_json_output_is_parseable():
    result = _run("--format", "json", str(FIXTURES / "bad_rules.yml"))
    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert data["finding_count"] > 0
    found_ids = {f["check_id"] for f in data["findings"]}
    assert "missing-for" in found_ids
    assert "counter-without-rate" in found_ids


def test_disable_suppresses_check():
    result = _run(
        "--disable", "missing-for,counter-without-rate",
        "--format", "json",
        str(FIXTURES / "bad_rules.yml"),
    )
    data = json.loads(result.stdout)
    ids = {f["check_id"] for f in data["findings"]}
    assert "missing-for" not in ids
    assert "counter-without-rate" not in ids


def test_enable_runs_exclusive_set():
    result = _run(
        "--enable", "missing-for",
        "--format", "json",
        str(FIXTURES / "bad_rules.yml"),
    )
    data = json.loads(result.stdout)
    ids = {f["check_id"] for f in data["findings"]}
    assert ids == {"missing-for"}


def test_unknown_check_id_errors_out():
    result = _run(
        "--disable", "not-a-real-check",
        str(FIXTURES / "bad_rules.yml"),
    )
    assert result.returncode == 2
    assert "unknown check id" in result.stderr.lower()


def test_fail_on_warning_raises_exit_code_for_warnings_only():
    # good_rules.yml has zero findings so it still exits 0
    r_good = _run("--fail-on", "warning", str(FIXTURES / "good_rules.yml"))
    assert r_good.returncode == 0
    # bad_rules.yml has findings at every severity; exit is 1
    r_bad = _run("--fail-on", "warning", str(FIXTURES / "bad_rules.yml"))
    assert r_bad.returncode == 1


def test_directory_argument_scans_recursively(tmp_path):
    # Place two rule files in a nested directory; CLI should scan both.
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "a.yml").write_text((FIXTURES / "good_rules.yml").read_text())
    (sub / "b.yml").write_text((FIXTURES / "good_rules.yml").read_text())
    result = _run(str(tmp_path))
    assert result.returncode == 0
    assert "2 file(s) scanned" in result.stdout


def test_list_checks_prints_registry():
    result = _run("--list-checks")
    assert result.returncode == 0
    for check_id in [
        "missing-for", "missing-annotations", "missing-severity-label",
        "short-rate-window", "counter-without-rate",
        "aggregation-drops-identifying-labels", "duplicate-alert-expression",
    ]:
        assert check_id in result.stdout
