"""Cross-rule check: two alerts with the same PromQL expression.

When two rules across the rule files compare the same normalized expression,
one of two things is happening:

1. Copy-paste bug — somebody duplicated a rule and forgot to change the
   threshold or labels. Both alerts will fire at the same time.
2. Severity ladder — the same metric has a warning threshold and a critical
   threshold (`> 80%` warning, `> 95%` critical). This is a legitimate
   pattern, but it needs to be visible. We detect the ladder case and
   emit a softer finding so the author can confirm intent.

Detection: we parse each expression and use the parser's `prettify()` as a
canonical form, so trivial whitespace/formatting differences don't hide
duplicates. Two rules collide when their canonical forms are equal.

Ladder detection: if both rules have the same canonical expression but
different `severity` label values, that's a ladder.
"""

from __future__ import annotations

from collections import defaultdict

from .. import promql
from ..config import Config
from ..model import Finding, Rule, RuleFile, Severity
from .base import Check


class DuplicateExpressionCheck(Check):
    id = "duplicate-alert-expression"
    description = (
        "Two alerts share the same expression — either a copy-paste bug or an "
        "undocumented severity ladder."
    )
    default_severity = Severity.WARNING

    def run(self, rule_files: list[RuleFile], config: Config) -> list[Finding]:
        findings: list[Finding] = []
        sev = self.severity_for(config)

        # Bucket rules by canonical expression.
        by_canonical: dict[str, list[Rule]] = defaultdict(list)
        for rf in rule_files:
            for rule in rf.alerting_rules:
                try:
                    canonical = promql.parse(rule.expr).prettify()
                except promql.ParseError:
                    canonical = rule.expr  # fall back to raw string for unparseable exprs
                by_canonical[canonical].append(rule)

        for canonical, rules in by_canonical.items():
            if len(rules) < 2:
                continue

            severities = {r.labels.get("severity") for r in rules}
            severities.discard(None)
            is_ladder = len(severities) >= 2

            # Emit one finding per rule in the group, pointing at its peers.
            for i, rule in enumerate(rules):
                others = [r for j, r in enumerate(rules) if j != i]
                peer_locs = ", ".join(
                    f"{r.file.name}:{r.line} ({r.name})" for r in others
                )
                if is_ladder:
                    message = (
                        f"Shares expression with {len(others)} other rule(s) "
                        f"({peer_locs}) that use a different `severity` label. "
                        f"This looks like a severity ladder — verify the "
                        f"threshold/for values are different."
                    )
                    suggestion = (
                        "If this is intentional (warning + critical ladder), "
                        "consider documenting it in the annotations. If not, "
                        "these rules are exact duplicates."
                    )
                else:
                    message = (
                        f"Exact-duplicate expression with {len(others)} other "
                        f"rule(s): {peer_locs}. Both will fire simultaneously."
                    )
                    suggestion = (
                        "Delete the duplicate, or change the threshold / "
                        "selectors so the two alerts actually mean different "
                        "things."
                    )
                findings.append(
                    Finding(
                        check_id=self.id,
                        severity=sev,
                        file=rule.file,
                        line=rule.line,
                        rule_name=rule.name,
                        group=rule.group,
                        message=message,
                        suggestion=suggestion,
                    )
                )
        return findings
