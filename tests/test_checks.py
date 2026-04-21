"""Per-check unit tests.

Each section below exercises one check in isolation, using small synthetic
RuleFile inputs for positive and negative cases. We also assert against the
shared `bad_rules.yml` fixture for end-to-end behavior — if a check stops
firing on its designated rule there, something regressed.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from promlint.checks import ALL_CHECKS
from promlint.checks.aggregation_labels import AggregationDropsLabelsCheck
from promlint.checks.counter_without_rate import CounterWithoutRateCheck
from promlint.checks.duplicate_expression import DuplicateExpressionCheck
from promlint.checks.missing_annotations import MissingAnnotationsCheck
from promlint.checks.missing_for import MissingForCheck
from promlint.checks.missing_severity_label import MissingSeverityLabelCheck
from promlint.checks.short_rate_window import ShortRateWindowCheck
from promlint.config import Config
from promlint.loader import load_rule_files
from promlint.model import Group, Rule, RuleFile, Severity


# --------------------------------------------------------------------------- #
#  Small helpers                                                              #
# --------------------------------------------------------------------------- #


_DEFAULT_LABELS = {"severity": "warning"}
_DEFAULT_ANNOTATIONS = {
    "summary": "s",
    "description": "d",
    "runbook_url": "http://r",
}


def _rule(
    *,
    name: str = "R",
    expr: str = "up == 0",
    for_duration: str | None = "5m",
    labels: dict[str, str] | None = None,
    annotations: dict[str, str] | None = None,
) -> Rule:
    return Rule(
        name=name,
        expr=expr,
        group="g",
        file=Path("test.yml"),
        line=1,
        for_duration=for_duration,
        # Use `is None` so callers can pass an explicit {} to mean "no labels/annotations"
        labels=_DEFAULT_LABELS if labels is None else labels,
        annotations=_DEFAULT_ANNOTATIONS if annotations is None else annotations,
    )


def _file(rules: list[Rule]) -> RuleFile:
    return RuleFile(path=Path("test.yml"), groups=(Group(name="g", interval=None, rules=tuple(rules)),))


# --------------------------------------------------------------------------- #
#  missing-for                                                                #
# --------------------------------------------------------------------------- #


class TestMissingFor:
    def test_flags_rule_without_for(self):
        rf = _file([_rule(name="NoFor", for_duration=None)])
        findings = MissingForCheck().run([rf], Config())
        assert len(findings) == 1
        assert findings[0].check_id == "missing-for"

    def test_does_not_flag_rule_with_for(self):
        rf = _file([_rule(name="HasFor", for_duration="5m")])
        assert MissingForCheck().run([rf], Config()) == []

    def test_allows_explicit_zero_for(self):
        rf = _file([_rule(name="Zero", for_duration="0s")])
        assert MissingForCheck().run([rf], Config()) == []


# --------------------------------------------------------------------------- #
#  missing-annotations                                                        #
# --------------------------------------------------------------------------- #


class TestMissingAnnotations:
    def test_flags_missing_summary_and_description_as_error(self):
        rf = _file([_rule(name="Bare", annotations={})])
        findings = MissingAnnotationsCheck().run([rf], Config())
        assert len(findings) == 2  # required + recommended
        errs = [f for f in findings if f.severity == Severity.ERROR]
        warns = [f for f in findings if f.severity == Severity.WARNING]
        assert len(errs) == 1 and "summary" in errs[0].message and "description" in errs[0].message
        assert len(warns) == 1 and "runbook_url" in warns[0].message

    def test_warning_only_when_required_present_but_recommended_missing(self):
        rf = _file([_rule(annotations={"summary": "x", "description": "y"})])
        findings = MissingAnnotationsCheck().run([rf], Config())
        assert len(findings) == 1
        assert findings[0].severity == Severity.WARNING

    def test_no_findings_when_all_annotations_present(self):
        rf = _file(
            [
                _rule(
                    annotations={
                        "summary": "s",
                        "description": "d",
                        "runbook_url": "http://r",
                    }
                )
            ]
        )
        assert MissingAnnotationsCheck().run([rf], Config()) == []

    def test_respects_config_overrides(self):
        rf = _file([_rule(annotations={"summary": "x", "description": "y"})])
        cfg = Config(recommended_annotations=frozenset())
        assert MissingAnnotationsCheck().run([rf], cfg) == []


# --------------------------------------------------------------------------- #
#  missing-severity-label                                                     #
# --------------------------------------------------------------------------- #


class TestMissingSeverityLabel:
    def test_flags_rule_with_no_labels(self):
        rf = _file([_rule(labels={})])
        findings = MissingSeverityLabelCheck().run([rf], Config())
        assert len(findings) == 1
        assert findings[0].severity == Severity.ERROR
        assert "severity" in findings[0].message

    def test_flags_typo_value(self):
        rf = _file([_rule(labels={"severity": "critcal"})])  # typo
        findings = MissingSeverityLabelCheck().run([rf], Config())
        assert len(findings) == 1
        assert "not one of the allowed values" in findings[0].message

    def test_accepts_allowed_value(self):
        rf = _file([_rule(labels={"severity": "critical"})])
        assert MissingSeverityLabelCheck().run([rf], Config()) == []


# --------------------------------------------------------------------------- #
#  short-rate-window                                                          #
# --------------------------------------------------------------------------- #


class TestShortRateWindow:
    def test_flags_sub_2m_window(self):
        rf = _file([_rule(expr="rate(errors_total[30s]) > 0")])
        findings = ShortRateWindowCheck().run([rf], Config())
        assert len(findings) == 1
        assert "30s" in findings[0].message

    def test_allows_window_at_minimum(self):
        rf = _file([_rule(expr="rate(errors_total[2m]) > 0")])
        assert ShortRateWindowCheck().run([rf], Config()) == []

    def test_flags_for_shorter_than_rate_window(self):
        rf = _file(
            [_rule(expr="rate(errors_total[5m]) > 0", for_duration="1m")]
        )
        findings = ShortRateWindowCheck().run([rf], Config())
        # The rate window is 5m (above minimum) but for:1m < 5m → one finding
        # for the for/window mismatch.
        assert len(findings) == 1
        assert "shorter than the longest rate window" in findings[0].message

    def test_unparseable_expr_is_skipped_silently(self):
        rf = _file([_rule(expr="((((")])
        assert ShortRateWindowCheck().run([rf], Config()) == []


# --------------------------------------------------------------------------- #
#  counter-without-rate                                                       #
# --------------------------------------------------------------------------- #


class TestCounterWithoutRate:
    def test_flags_bare_total_comparison(self):
        rf = _file([_rule(expr="http_requests_total > 100")])
        findings = CounterWithoutRateCheck().run([rf], Config())
        assert len(findings) == 1
        assert "http_requests_total" in findings[0].message

    def test_does_not_flag_rate_wrapped(self):
        rf = _file([_rule(expr="rate(http_requests_total[5m]) > 1")])
        assert CounterWithoutRateCheck().run([rf], Config()) == []

    def test_does_not_flag_non_counter_metric(self):
        rf = _file([_rule(expr="http_requests_in_flight > 100")])
        assert CounterWithoutRateCheck().run([rf], Config()) == []

    def test_deduplicates_per_metric_name(self):
        # Same counter appears twice: one rule, one finding
        rf = _file([_rule(expr="http_requests_total / http_requests_total > 1")])
        findings = CounterWithoutRateCheck().run([rf], Config())
        assert len(findings) == 1


# --------------------------------------------------------------------------- #
#  aggregation-drops-identifying-labels                                       #
# --------------------------------------------------------------------------- #


class TestAggregationDropsLabels:
    def test_flags_bare_sum(self):
        rf = _file([_rule(expr="sum(rate(errors_total[5m])) > 100")])
        findings = AggregationDropsLabelsCheck().run([rf], Config())
        assert len(findings) == 1
        assert "sum" in findings[0].message

    def test_ok_with_by_identifying(self):
        rf = _file(
            [_rule(expr="sum by (service) (rate(errors_total[5m])) > 100")]
        )
        assert AggregationDropsLabelsCheck().run([rf], Config()) == []

    def test_ok_with_without_non_identifying(self):
        # `without (dc)` keeps service/instance/etc. → ok
        rf = _file(
            [
                _rule(
                    expr="sum without (dc) (rate(errors_total[5m])) > 100"
                )
            ]
        )
        assert AggregationDropsLabelsCheck().run([rf], Config()) == []

    def test_flags_with_only_non_identifying_by(self):
        rf = _file(
            [_rule(expr="sum by (code) (rate(errors_total[5m])) > 100")]
        )
        findings = AggregationDropsLabelsCheck().run([rf], Config())
        assert len(findings) == 1


# --------------------------------------------------------------------------- #
#  duplicate-alert-expression                                                 #
# --------------------------------------------------------------------------- #


class TestDuplicateExpression:
    def test_flags_exact_duplicate(self):
        rf = _file(
            [
                _rule(name="A", expr="up == 0"),
                _rule(name="B", expr="up == 0"),
            ]
        )
        findings = DuplicateExpressionCheck().run([rf], Config())
        # One finding per offending rule
        assert len(findings) == 2
        assert all("duplicate" in f.message.lower() for f in findings)

    def test_flags_ladder_with_different_severity(self):
        rf = _file(
            [
                _rule(name="A", expr="up == 0", labels={"severity": "warning"}),
                _rule(name="B", expr="up == 0", labels={"severity": "critical"}),
            ]
        )
        findings = DuplicateExpressionCheck().run([rf], Config())
        assert len(findings) == 2
        assert all("ladder" in f.message.lower() for f in findings)

    def test_ignores_different_expressions(self):
        rf = _file(
            [
                _rule(name="A", expr="up == 0"),
                _rule(name="B", expr="up == 1"),
            ]
        )
        assert DuplicateExpressionCheck().run([rf], Config()) == []

    def test_whitespace_variations_collapse(self):
        rf = _file(
            [
                _rule(name="A", expr="up  ==  0"),
                _rule(name="B", expr="up == 0"),
            ]
        )
        findings = DuplicateExpressionCheck().run([rf], Config())
        assert len(findings) == 2


# --------------------------------------------------------------------------- #
#  End-to-end: every check fires against bad_rules.yml                        #
# --------------------------------------------------------------------------- #


def test_every_check_has_at_least_one_finding_in_bad_fixture(bad_rules_path: Path):
    rule_files, _ = load_rule_files([bad_rules_path])
    firing_ids: set[str] = set()
    for check in ALL_CHECKS:
        findings = check.run(rule_files, Config())
        if findings:
            firing_ids.add(check.id)
    # Every check should trigger at least once against the curated bad fixture
    assert firing_ids == {c.id for c in ALL_CHECKS}


def test_good_fixture_produces_no_findings(good_rules_path: Path):
    rule_files, _ = load_rule_files([good_rules_path])
    for check in ALL_CHECKS:
        findings = check.run(rule_files, Config())
        assert findings == [], f"{check.id} flagged the good fixture: {findings}"
