"""Flag alerting rules that have no `for:` clause.

An alert with no `for:` fires on the first evaluation cycle where the
expression returns any samples. A single scrape spike or a brief network
wobble pages on-call. Requiring a `for:` value forces the author to decide
"how long must this condition hold before it's real?".

We intentionally do NOT flag `for: 0s` — that's an explicit opt-in for
discrete events (e.g. "deployment failed", "backup script exited non-zero")
where a single evaluation is the whole signal.
"""

from __future__ import annotations

from ..config import Config
from ..model import Finding, RuleFile, Severity
from .base import Check


class MissingForCheck(Check):
    id = "missing-for"
    description = "Alerting rule has no `for:` clause; fires on a single scrape."
    default_severity = Severity.WARNING

    def run(self, rule_files: list[RuleFile], config: Config) -> list[Finding]:
        findings: list[Finding] = []
        sev = self.severity_for(config)
        for rf in rule_files:
            for rule in rf.alerting_rules:
                if rule.for_duration is None:
                    findings.append(
                        Finding(
                            check_id=self.id,
                            severity=sev,
                            file=rule.file,
                            line=rule.line,
                            rule_name=rule.name,
                            group=rule.group,
                            message=(
                                "Alert has no `for:` clause; it will fire on the "
                                "first scrape where the expression is true, which "
                                "is almost always noisier than intended."
                            ),
                            suggestion=(
                                "Add `for: 5m` (or similar) so the condition must "
                                "hold before paging. Use `for: 0s` to explicitly "
                                "opt in to instant firing for discrete events."
                            ),
                        )
                    )
        return findings
