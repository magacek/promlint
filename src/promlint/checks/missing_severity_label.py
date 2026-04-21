"""Flag alerts with no `severity` label or a severity value Alertmanager won't
route on.

Alertmanager configs almost universally route based on `severity` — `critical`
pages PagerDuty, `warning` goes to Slack, `info` goes to a mailbox. An alert
missing the label silently falls through to whatever the catch-all route is,
which in practice means either spamming the wrong channel or being dropped.

We check two things:
1. The `severity` label (or whatever labels the config declares required) is set.
2. The severity value is in the team's allowed set (default: critical/warning/info).

(1) is almost always a bug. (2) catches typos like `severity: critcal`.
"""

from __future__ import annotations

from ..config import Config
from ..model import Finding, RuleFile, Severity
from .base import Check


class MissingSeverityLabelCheck(Check):
    id = "missing-severity-label"
    description = (
        "Alert is missing the `severity` label Alertmanager routes on, or uses "
        "an unexpected value."
    )
    default_severity = Severity.ERROR

    def run(self, rule_files: list[RuleFile], config: Config) -> list[Finding]:
        findings: list[Finding] = []
        sev = self.severity_for(config)

        for rf in rule_files:
            for rule in rf.alerting_rules:
                for required in config.required_labels:
                    if required not in rule.labels:
                        findings.append(
                            Finding(
                                check_id=self.id,
                                severity=sev,
                                file=rule.file,
                                line=rule.line,
                                rule_name=rule.name,
                                group=rule.group,
                                message=(
                                    f"Missing required label `{required}`. "
                                    f"Alertmanager routing will fall through to "
                                    f"the default receiver."
                                ),
                                suggestion=(
                                    f"Add `labels: {{ {required}: warning }}` "
                                    f"(or the appropriate value for this alert)."
                                ),
                            )
                        )

                if "severity" in rule.labels:
                    value = rule.labels["severity"]
                    if value not in config.valid_severity_values:
                        allowed = ", ".join(sorted(config.valid_severity_values))
                        findings.append(
                            Finding(
                                check_id=self.id,
                                severity=sev,
                                file=rule.file,
                                line=rule.line,
                                rule_name=rule.name,
                                group=rule.group,
                                message=(
                                    f"`severity: {value}` is not one of the "
                                    f"allowed values ({allowed}). Likely a typo "
                                    f"— Alertmanager won't match it on any route."
                                ),
                                suggestion=(
                                    f"Use one of: {allowed}, or update the "
                                    f"`valid_severity_values` config."
                                ),
                            )
                        )
        return findings
