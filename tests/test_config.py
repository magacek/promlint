from datetime import timedelta
from pathlib import Path

import pytest

from promlint.config import Config, load_config, _parse_duration
from promlint.model import Severity


def test_defaults():
    c = Config()
    assert c.fail_on == Severity.ERROR
    assert c.min_rate_window == timedelta(minutes=2)
    assert "summary" in c.required_annotations
    assert "severity" in c.required_labels


def test_load_config_none_returns_defaults():
    c = load_config(None)
    assert c == Config()


def test_load_config_overrides_fields(tmp_path: Path):
    cfg = tmp_path / "promlint.yml"
    cfg.write_text(
        """
disabled_checks: [missing-for, counter-without-rate]
required_annotations: [summary]
recommended_annotations: []
valid_severity_values: [page, ticket]
min_rate_window: 5m
identifying_labels: [service]
fail_on: warning
severity_overrides:
  missing-annotations: warning
"""
    )
    c = load_config(cfg)
    assert c.disabled_checks == frozenset({"missing-for", "counter-without-rate"})
    assert c.required_annotations == frozenset({"summary"})
    assert c.recommended_annotations == frozenset()
    assert c.valid_severity_values == frozenset({"page", "ticket"})
    assert c.min_rate_window == timedelta(minutes=5)
    assert c.identifying_labels == frozenset({"service"})
    assert c.fail_on == Severity.WARNING
    assert c.severity_overrides == {"missing-annotations": Severity.WARNING}


@pytest.mark.parametrize(
    "s, expected",
    [
        ("30s", timedelta(seconds=30)),
        ("2m", timedelta(minutes=2)),
        ("1h", timedelta(hours=1)),
        ("1d", timedelta(days=1)),
        (45, timedelta(seconds=45)),
    ],
)
def test_parse_duration(s, expected):
    assert _parse_duration(s) == expected


def test_parse_duration_invalid_unit():
    with pytest.raises(ValueError):
        _parse_duration("5y")


def test_severity_from_str_invalid():
    with pytest.raises(ValueError):
        Severity.from_str("catastrophic")
