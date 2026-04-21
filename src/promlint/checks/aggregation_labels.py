"""Flag aggregations that drop every identifying label.

`sum(rate(http_errors_total[5m])) > 100` fires a single alert when errors
exceed 100 across the whole fleet. On-call sees "errors are high" and has
no idea which service, pod, or instance is actually failing. The fix is
almost always a `by (...)` clause naming whichever identifying label the
user cares about.

The AST is what makes this check correct — regex can't cleanly tell
`sum by (job)` from `sum(job)` (a count) from `sum without (instance)`.
We walk every AggregateExpr in the expression and flag the ones that don't
preserve at least one of the configured identifying labels.

False-positive risk: legitimate global counters like
`sum(up{job="prom"}) < 2` ("is at least 2 Prometheus replicas up?"). The
check will flag these. A team that uses them heavily can disable this
check or tune `identifying_labels`.
"""

from __future__ import annotations

from .. import promql
from ..config import Config
from ..model import Finding, RuleFile, Severity
from .base import Check


class AggregationDropsLabelsCheck(Check):
    id = "aggregation-drops-identifying-labels"
    description = (
        "Aggregation drops every identifying label; resulting alert won't tell "
        "on-call what's actually broken."
    )
    default_severity = Severity.WARNING

    def run(self, rule_files: list[RuleFile], config: Config) -> list[Finding]:
        findings: list[Finding] = []
        sev = self.severity_for(config)
        id_labels = config.identifying_labels

        for rf in rule_files:
            for rule in rf.alerting_rules:
                try:
                    ast = promql.parse(rule.expr)
                except promql.ParseError:
                    continue

                aggs = promql.find_aggregations(ast)
                # Report one finding per rule, even if multiple aggregations are
                # problematic — the remediation is almost always the same.
                bad = [a for a in aggs if not promql.aggregation_preserves_any(a, id_labels)]
                if bad:
                    ops = ", ".join(sorted({a.op for a in bad}))
                    findings.append(
                        Finding(
                            check_id=self.id,
                            severity=sev,
                            file=rule.file,
                            line=rule.line,
                            rule_name=rule.name,
                            group=rule.group,
                            message=(
                                f"`{ops}(...)` aggregates away all identifying "
                                f"labels ({', '.join(sorted(id_labels))}). This "
                                f"alert will fire once for the whole fleet and "
                                f"won't tell on-call which service/pod/instance "
                                f"is affected."
                            ),
                            suggestion=(
                                "Add a `by (...)` clause naming at least one "
                                "identifying label, e.g. `sum by (service, "
                                "instance) (...)`."
                            ),
                        )
                    )
        return findings
