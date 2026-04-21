"""Flag alerting rules that lack the annotations an on-call engineer needs.

When a page fires at 3am, the on-call engineer sees the alert name and
whatever annotations are attached. No `summary` or `description` means
they're starting from zero.

Two tiers:
- `required_annotations` (default: summary, description) → error. The alert
  is meaningfully broken without these.
- `recommended_annotations` (default: runbook_url) → warning. Nice-to-have;
  teams that don't have runbooks can disable this via config.
"""

from __future__ import annotations

from ..config import Config
from ..model import Finding, RuleFile, Severity
from .base import Check


class MissingAnnotationsCheck(Check):
    id = "missing-annotations"
    description = (
        "Alerting rule is missing annotations on-call needs to understand the page."
    )
    default_severity = Severity.ERROR  # severity for required; recommended uses WARNING

    def run(self, rule_files: list[RuleFile], config: Config) -> list[Finding]:
        findings: list[Finding] = []
        error_sev = self.severity_for(config)
        # Recommended annotations are always reported at one severity level below
        # whatever the required-severity is. If required is ERROR (the default),
        # recommended is WARNING. This keeps the two-tier behavior intact even
        # when the user overrides the severity.
        warn_sev = _one_level_below(error_sev)

        req = config.required_annotations
        rec = config.recommended_annotations

        for rf in rule_files:
            for rule in rf.alerting_rules:
                present = set(rule.annotations.keys())
                missing_required = sorted(req - present)
                missing_recommended = sorted(rec - present)

                if missing_required:
                    findings.append(
                        Finding(
                            check_id=self.id,
                            severity=error_sev,
                            file=rule.file,
                            line=rule.line,
                            rule_name=rule.name,
                            group=rule.group,
                            message=(
                                f"Missing required annotation(s): "
                                f"{', '.join(missing_required)}. On-call will see "
                                f"only the alert name."
                            ),
                            suggestion=(
                                "Add `annotations: { summary: '...', description: "
                                "'...' }` so the page carries context."
                            ),
                        )
                    )

                if missing_recommended:
                    findings.append(
                        Finding(
                            check_id=self.id,
                            severity=warn_sev,
                            file=rule.file,
                            line=rule.line,
                            rule_name=rule.name,
                            group=rule.group,
                            message=(
                                f"Missing recommended annotation(s): "
                                f"{', '.join(missing_recommended)}."
                            ),
                            suggestion=(
                                "Add a `runbook_url` so on-call can jump straight "
                                "to mitigation steps."
                            ),
                        )
                    )
        return findings


def _one_level_below(s: Severity) -> Severity:
    if s == Severity.ERROR:
        return Severity.WARNING
    if s == Severity.WARNING:
        return Severity.INFO
    return Severity.INFO
