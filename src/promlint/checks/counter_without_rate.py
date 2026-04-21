"""Flag counters compared directly instead of via rate()/increase().

Prometheus counters (metrics whose name ends in `_total` by convention) only
grow and reset on process restart. Writing `http_requests_total > 1000` is
almost always a bug: on a freshly-restarted process the counter is 0;
elsewhere it grew past 1000 days ago and stays true forever. What you
actually wanted is `rate(http_requests_total[5m]) > 1000/300`.

We detect this via the AST: any VectorSelector whose name ends in `_total`
that is NOT inside a rate/irate/increase/delta/resets call. The `_total`
naming convention is the only reliable static signal we have.

False-positive risk: someone could name a gauge `foo_total`. The `_total`
convention says this is a bug in the metric name itself, so the finding is
still useful.
"""

from __future__ import annotations

from .. import promql
from ..config import Config
from ..model import Finding, RuleFile, Severity
from .base import Check


class CounterWithoutRateCheck(Check):
    id = "counter-without-rate"
    description = (
        "Alert compares a counter metric (_total) directly instead of wrapping "
        "it in rate()/increase()."
    )
    default_severity = Severity.ERROR

    def run(self, rule_files: list[RuleFile], config: Config) -> list[Finding]:
        findings: list[Finding] = []
        sev = self.severity_for(config)

        for rf in rule_files:
            for rule in rf.alerting_rules:
                try:
                    ast = promql.parse(rule.expr)
                except promql.ParseError:
                    continue

                bare = promql.find_bare_counters(ast)
                # Dedupe per metric name — one finding per counter per rule
                seen: set[str] = set()
                for b in bare:
                    if b.metric_name in seen:
                        continue
                    seen.add(b.metric_name)
                    findings.append(
                        Finding(
                            check_id=self.id,
                            severity=sev,
                            file=rule.file,
                            line=rule.line,
                            rule_name=rule.name,
                            group=rule.group,
                            message=(
                                f"`{b.metric_name}` looks like a counter but is "
                                f"not wrapped in rate/increase/irate. Counters "
                                f"only grow and reset on restart, so direct "
                                f"comparisons fire indefinitely or not at all."
                            ),
                            suggestion=(
                                f"Use e.g. `rate({b.metric_name}[5m])` or "
                                f"`increase({b.metric_name}[1h])` depending on "
                                f"what you're alerting on."
                            ),
                        )
                    )
        return findings
