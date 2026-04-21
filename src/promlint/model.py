from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class Severity(str, Enum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"

    @property
    def rank(self) -> int:
        return {"error": 3, "warning": 2, "info": 1}[self.value]

    @classmethod
    def from_str(cls, s: str) -> "Severity":
        try:
            return cls(s.lower())
        except ValueError as exc:
            raise ValueError(
                f"unknown severity {s!r}; expected one of: {[m.value for m in cls]}"
            ) from exc


@dataclass(frozen=True)
class Rule:
    """A single Prometheus alerting rule."""

    name: str
    expr: str
    group: str
    file: Path
    line: int
    for_duration: str | None = None
    keep_firing_for: str | None = None
    labels: dict[str, str] = field(default_factory=dict)
    annotations: dict[str, str] = field(default_factory=dict)

    @property
    def location(self) -> str:
        return f"{self.file}:{self.line}"


@dataclass(frozen=True)
class Group:
    name: str
    interval: str | None
    rules: tuple[Rule, ...]


@dataclass(frozen=True)
class RuleFile:
    path: Path
    groups: tuple[Group, ...]

    @property
    def alerting_rules(self) -> list[Rule]:
        return [r for g in self.groups for r in g.rules]


@dataclass(frozen=True)
class Finding:
    check_id: str
    severity: Severity
    file: Path
    line: int
    rule_name: str
    group: str
    message: str
    suggestion: str = ""

    def to_dict(self) -> dict:
        return {
            "check_id": self.check_id,
            "severity": self.severity.value,
            "file": str(self.file),
            "line": self.line,
            "rule_name": self.rule_name,
            "group": self.group,
            "message": self.message,
            "suggestion": self.suggestion,
        }
