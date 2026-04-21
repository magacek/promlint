import io
import json
from pathlib import Path

from promlint.model import Finding, Severity
from promlint.report import JsonReporter, TextReporter


def _sample_findings() -> list[Finding]:
    return [
        Finding(
            check_id="missing-for",
            severity=Severity.WARNING,
            file=Path("rules.yml"),
            line=5,
            rule_name="NoForClause",
            group="g",
            message="No `for:` clause.",
            suggestion="Add `for: 5m`.",
        ),
        Finding(
            check_id="missing-severity-label",
            severity=Severity.ERROR,
            file=Path("rules.yml"),
            line=12,
            rule_name="Other",
            group="g",
            message="No severity.",
            suggestion="Add labels.",
        ),
    ]


def test_text_reporter_groups_by_file_and_prints_summary():
    buf = io.StringIO()
    TextReporter(color=False, stream=buf).write(_sample_findings(), scanned_files=1)
    out = buf.getvalue()
    assert "rules.yml" in out
    assert "WARN" in out and "ERROR" in out
    assert "NoForClause" in out
    assert "[missing-for]" in out
    assert "1 file(s) scanned" in out
    # Summary mentions both severities
    assert "1 error" in out and "1 warning" in out


def test_text_reporter_no_findings_message():
    buf = io.StringIO()
    TextReporter(color=False, stream=buf).write([], scanned_files=2)
    assert "no findings" in buf.getvalue().lower()


def test_json_reporter_produces_valid_schema():
    buf = io.StringIO()
    JsonReporter(stream=buf).write(_sample_findings(), scanned_files=3)
    data = json.loads(buf.getvalue())
    assert data["scanned_files"] == 3
    assert data["finding_count"] == 2
    assert len(data["findings"]) == 2
    first = data["findings"][0]
    # Required schema keys
    assert set(first.keys()) == {
        "check_id", "severity", "file", "line", "rule_name",
        "group", "message", "suggestion",
    }
