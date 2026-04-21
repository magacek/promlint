from datetime import timedelta

import pytest

from promlint import promql


def test_parse_valid_expression_returns_ast():
    ast = promql.parse("rate(x[5m]) > 10")
    assert ast is not None


def test_parse_invalid_expression_raises_parse_error():
    with pytest.raises(promql.ParseError):
        promql.parse("this is not ))( valid")


def test_find_bare_counters_catches_direct_comparison():
    ast = promql.parse("http_requests_total > 100")
    bare = promql.find_bare_counters(ast)
    assert [b.metric_name for b in bare] == ["http_requests_total"]


def test_find_bare_counters_ignores_rate_wrapped():
    for wrapper in ("rate(http_requests_total[5m])", "increase(http_requests_total[1h])", "irate(http_requests_total[1m])"):
        ast = promql.parse(f"{wrapper} > 10")
        assert promql.find_bare_counters(ast) == []


def test_find_bare_counters_ignores_non_counter_name():
    ast = promql.parse("http_requests_in_flight > 100")
    assert promql.find_bare_counters(ast) == []


def test_find_rate_calls_returns_windows():
    ast = promql.parse("sum(rate(a[5m])) / sum(rate(b[30s]))")
    calls = promql.find_rate_calls(ast)
    windows = sorted(c.window for c in calls)
    assert windows == [timedelta(seconds=30), timedelta(minutes=5)]


def test_aggregation_preserves_any_by_clause():
    aggs = promql.find_aggregations(promql.parse("sum by (service) (x)"))
    assert promql.aggregation_preserves_any(aggs[0], frozenset({"service", "instance"})) is True


def test_aggregation_drops_all_without_modifier():
    aggs = promql.find_aggregations(promql.parse("sum(x)"))
    assert promql.aggregation_preserves_any(aggs[0], frozenset({"service"})) is False


def test_aggregation_preserves_any_without_clause():
    # without (instance) → keeps service, job, etc.
    aggs = promql.find_aggregations(promql.parse("sum without (instance) (x)"))
    assert promql.aggregation_preserves_any(aggs[0], frozenset({"service"})) is True


def test_aggregation_without_drops_only_listed():
    # without (service) → service is dropped, nothing else identifying is preserved
    aggs = promql.find_aggregations(promql.parse("sum without (service) (x)"))
    assert (
        promql.aggregation_preserves_any(aggs[0], frozenset({"service"}))
        is False
    )


def test_nested_expressions_are_walked():
    expr = "sum by (job) (rate(errors_total[5m])) / sum by (job) (rate(total_total[5m]))"
    ast = promql.parse(expr)
    aggs = promql.find_aggregations(ast)
    assert len(aggs) == 2
    rate_calls = promql.find_rate_calls(ast)
    assert len(rate_calls) == 2
    # Bare counters should be empty because both are rate-wrapped.
    assert promql.find_bare_counters(ast) == []
