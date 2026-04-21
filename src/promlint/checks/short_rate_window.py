"""Flag rate/increase windows that are too short to be statistically meaningful.

`rate(m[1m])` looks fine on paper but with a 30s scrape interval Prometheus
has only ~2 samples to work with — a single missed scrape produces a wildly
wrong rate. The usual guidance is that a rate window should be at least
~4× the scrape interval. We default to a 2-minute minimum; tune via
`min_rate_window` in config.

Plus a bonus anti-pattern: `for:` shorter than the rate window. Using
`rate(m[5m])` with `for: 1m` means the alert can fire before the rate window
has fully filled with post-event data — the very first "true" evaluation is
based on mostly stale data. Better to set `for:` >= the rate window.
"""

from __future__ import annotations

from datetime import timedelta

from .. import promql
from ..config import Config
from ..model import Finding, RuleFile, Severity
from .base import Check


class ShortRateWindowCheck(Check):
    id = "short-rate-window"
    description = (
        "rate()/increase() window is shorter than the configured minimum, or "
        "`for:` is shorter than the rate window."
    )
    default_severity = Severity.WARNING

    def run(self, rule_files: list[RuleFile], config: Config) -> list[Finding]:
        findings: list[Finding] = []
        sev = self.severity_for(config)
        min_window = config.min_rate_window

        for rf in rule_files:
            for rule in rf.alerting_rules:
                try:
                    ast = promql.parse(rule.expr)
                except promql.ParseError:
                    continue  # parse errors are surfaced by a different check path

                calls = promql.find_rate_calls(ast)
                for call in calls:
                    if call.window < min_window:
                        findings.append(
                            Finding(
                                check_id=self.id,
                                severity=sev,
                                file=rule.file,
                                line=rule.line,
                                rule_name=rule.name,
                                group=rule.group,
                                message=(
                                    f"`{call.function}(...[{_fmt(call.window)}])` "
                                    f"window is shorter than the configured "
                                    f"minimum ({_fmt(min_window)}). Rate windows "
                                    f"shorter than ~4× the scrape interval are "
                                    f"statistically noisy."
                                ),
                                suggestion=(
                                    f"Increase the range to at least "
                                    f"{_fmt(min_window)}, e.g. "
                                    f"`{call.function}(metric[{_fmt(min_window)}])`."
                                ),
                            )
                        )

                # `for:` < rate window is the other half of this family.
                if rule.for_duration and calls:
                    for_td = _parse_duration_loose(rule.for_duration)
                    if for_td is not None:
                        longest = max(c.window for c in calls)
                        if for_td > timedelta(0) and for_td < longest:
                            findings.append(
                                Finding(
                                    check_id=self.id,
                                    severity=sev,
                                    file=rule.file,
                                    line=rule.line,
                                    rule_name=rule.name,
                                    group=rule.group,
                                    message=(
                                        f"`for: {rule.for_duration}` is shorter "
                                        f"than the longest rate window "
                                        f"({_fmt(longest)}). The alert can fire "
                                        f"before the rate window has filled with "
                                        f"post-event data."
                                    ),
                                    suggestion=(
                                        f"Set `for:` >= the rate window "
                                        f"({_fmt(longest)} or longer)."
                                    ),
                                )
                            )
        return findings


def _fmt(d: timedelta) -> str:
    """Render a timedelta the way Prometheus users expect: 5m, 30s, 1h."""
    total = int(d.total_seconds())
    if total == 0:
        return "0s"
    if total % 3600 == 0:
        return f"{total // 3600}h"
    if total % 60 == 0:
        return f"{total // 60}m"
    return f"{total}s"


def _parse_duration_loose(s: str) -> timedelta | None:
    """Parse a Prometheus-style duration. Returns None if we can't."""
    s = s.strip()
    if not s:
        return None
    # Prom durations can be compound: 1h30m. Keep it simple and handle the
    # single-unit case, which is what ~all real rules use.
    try:
        unit = s[-1]
        val = float(s[:-1])
    except (ValueError, IndexError):
        return None
    table = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}
    if unit not in table:
        return None
    return timedelta(seconds=val * table[unit])
