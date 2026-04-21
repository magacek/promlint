"""Configuration for a promlint run.

Defaults live here; a user config file (YAML) and CLI flags override them.
Precedence: CLI flags > config file > defaults.

Every check reads what it needs off of this object. Severity overrides are
keyed by check ID, so a team can for example downgrade `missing-annotations`
from error to warning without forking the check.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import timedelta
from pathlib import Path

from ruamel.yaml import YAML

from .model import Severity


@dataclass(frozen=True)
class Config:
    # Which checks to run. Empty set means "all enabled checks".
    disabled_checks: frozenset[str] = frozenset()

    # Per-check severity overrides: {"missing-for": Severity.INFO}
    severity_overrides: dict[str, Severity] = field(default_factory=dict)

    # `missing-annotations` check: what must be present?
    required_annotations: frozenset[str] = frozenset({"summary", "description"})
    recommended_annotations: frozenset[str] = frozenset({"runbook_url"})

    # `missing-severity-label` check: what values are acceptable?
    required_labels: frozenset[str] = frozenset({"severity"})
    valid_severity_values: frozenset[str] = frozenset({"critical", "warning", "info"})

    # `short-rate-window` check
    min_rate_window: timedelta = timedelta(minutes=2)

    # `aggregation-drops-identifying-labels` check
    identifying_labels: frozenset[str] = frozenset(
        {"instance", "pod", "service", "job", "cluster", "namespace", "node"}
    )

    # Fail exit code if any finding has severity >= this threshold.
    fail_on: Severity = Severity.ERROR


def load_config(path: Path | None) -> Config:
    """Load a config file from disk, merging it over the defaults.

    If `path` is None, returns the defaults unchanged.
    """
    if path is None:
        return Config()

    yaml = YAML(typ="safe")
    with path.open("r", encoding="utf-8") as f:
        data = yaml.load(f) or {}

    cfg = Config()
    overrides: dict = {}

    if "disabled_checks" in data:
        overrides["disabled_checks"] = frozenset(data["disabled_checks"])
    if "required_annotations" in data:
        overrides["required_annotations"] = frozenset(data["required_annotations"])
    if "recommended_annotations" in data:
        overrides["recommended_annotations"] = frozenset(
            data["recommended_annotations"]
        )
    if "valid_severity_values" in data:
        overrides["valid_severity_values"] = frozenset(data["valid_severity_values"])
    if "min_rate_window" in data:
        overrides["min_rate_window"] = _parse_duration(data["min_rate_window"])
    if "identifying_labels" in data:
        overrides["identifying_labels"] = frozenset(data["identifying_labels"])
    if "fail_on" in data:
        overrides["fail_on"] = Severity.from_str(data["fail_on"])
    if "severity_overrides" in data:
        overrides["severity_overrides"] = {
            k: Severity.from_str(v) for k, v in data["severity_overrides"].items()
        }

    return replace(cfg, **overrides)


def _parse_duration(s: str | int | float) -> timedelta:
    """Parse short Prometheus-style durations (2m, 30s, 1h)."""
    if isinstance(s, (int, float)):
        return timedelta(seconds=float(s))
    s = s.strip()
    if not s:
        raise ValueError("empty duration")
    unit = s[-1]
    value = float(s[:-1])
    if unit == "s":
        return timedelta(seconds=value)
    if unit == "m":
        return timedelta(minutes=value)
    if unit == "h":
        return timedelta(hours=value)
    if unit == "d":
        return timedelta(days=value)
    raise ValueError(f"unsupported duration unit in {s!r}")
