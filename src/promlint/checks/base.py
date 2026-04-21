"""Check base class and a tiny helper for applying severity overrides."""

from __future__ import annotations

from abc import ABC, abstractmethod

from ..config import Config
from ..model import Finding, RuleFile, Severity


class Check(ABC):
    """A single check. Subclasses set the class attributes and implement `run`.

    A check returns a list of Findings. Single-rule checks typically loop over
    `rf.alerting_rules` internally; cross-rule checks consume `rule_files` as a
    whole.
    """

    id: str = ""
    description: str = ""
    default_severity: Severity = Severity.WARNING

    def severity_for(self, config: Config) -> Severity:
        return config.severity_overrides.get(self.id, self.default_severity)

    @abstractmethod
    def run(self, rule_files: list[RuleFile], config: Config) -> list[Finding]: ...
