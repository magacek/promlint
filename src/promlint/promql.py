"""PromQL AST helpers built on top of the `promql-parser` (PyO3) binding.

The checks that actually need PromQL semantics go through this module:

- `counter-without-rate`: identify VectorSelectors whose name looks like a
  counter (`*_total`) and that are NOT already inside a rate/irate/increase call.
- `short-rate-window`: pull the range duration out of every rate-like call.
- `aggregation-drops-identifying-labels`: find AggregateExpr nodes and decide
  whether their by/without modifier preserves at least one identifying label.

We pre-traverse the tree ourselves instead of trying to plug into whatever the
Rust parser exposes — the public Python API doesn't surface a visitor, just
node attributes. Walking manually keeps this file the sole place that cares
about the parser's shape.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Iterator

import promql_parser as pp


# Functions that wrap a counter to produce a rate/increase/derivative.
# If a counter selector is inside one of these, comparing the result is fine.
RATE_LIKE_FUNCTIONS: frozenset[str] = frozenset(
    {"rate", "irate", "increase", "delta", "idelta", "deriv", "resets"}
)

# Labels that typically identify where a problem is coming from. If an
# aggregation drops all of these, the resulting alert won't tell on-call
# which service / pod / instance is actually broken.
IDENTIFYING_LABELS: frozenset[str] = frozenset(
    {"instance", "pod", "service", "job", "cluster", "namespace", "node"}
)


class ParseError(ValueError):
    """Wrapper so callers don't have to import the Rust parser's exception type."""


def parse(expr: str):
    """Parse a PromQL expression and return the AST root node.

    Raises:
        ParseError: if the expression is not valid PromQL.
    """
    try:
        return pp.parse(expr)
    except Exception as exc:  # the binding raises a generic Exception
        raise ParseError(str(exc)) from exc


# --------------------------------------------------------------------------- #
#  Tree traversal                                                             #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class WalkItem:
    node: object
    inside_rate: bool  # True if any ancestor is a rate-like Call


def walk(node, *, inside_rate: bool = False) -> Iterator[WalkItem]:
    """Yield every subexpression, propagating an `inside_rate` flag.

    `inside_rate` is True when the current node descends from a call to
    rate/increase/irate/delta/etc. Useful for the counter-without-rate check.
    """
    yield WalkItem(node=node, inside_rate=inside_rate)

    if isinstance(node, pp.BinaryExpr):
        yield from walk(node.lhs, inside_rate=inside_rate)
        yield from walk(node.rhs, inside_rate=inside_rate)
    elif isinstance(node, pp.UnaryExpr):
        yield from walk(node.expr, inside_rate=inside_rate)
    elif isinstance(node, pp.ParenExpr):
        yield from walk(node.expr, inside_rate=inside_rate)
    elif isinstance(node, pp.SubqueryExpr):
        yield from walk(node.expr, inside_rate=inside_rate)
    elif isinstance(node, pp.AggregateExpr):
        yield from walk(node.expr, inside_rate=inside_rate)
        if node.param is not None:
            yield from walk(node.param, inside_rate=inside_rate)
    elif isinstance(node, pp.Call):
        next_inside = inside_rate or (node.func.name in RATE_LIKE_FUNCTIONS)
        for arg in node.args:
            yield from walk(arg, inside_rate=next_inside)
    elif isinstance(node, pp.MatrixSelector):
        yield from walk(node.vector_selector, inside_rate=inside_rate)
    # leaves: VectorSelector, NumberLiteral, StringLiteral -> no recursion


# --------------------------------------------------------------------------- #
#  Check-specific helpers                                                     #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class BareCounter:
    """A counter-named vector selector that is NOT inside a rate-like call."""

    metric_name: str


def find_bare_counters(ast) -> list[BareCounter]:
    """Return counter-like VectorSelectors that are used outside a rate function.

    We treat a metric as a counter if its name ends in `_total` — this is the
    Prometheus naming convention and the only reliable signal we have from
    static analysis alone.
    """
    found: list[BareCounter] = []
    for item in walk(ast):
        if isinstance(item.node, pp.VectorSelector) and not item.inside_rate:
            name = item.node.name or ""
            if name.endswith("_total"):
                found.append(BareCounter(metric_name=name))
    return found


@dataclass(frozen=True)
class RateCall:
    """A rate/irate/increase/etc. call and the range it was given."""

    function: str
    window: timedelta


def find_rate_calls(ast) -> list[RateCall]:
    """Return every rate-like call with its range duration."""
    found: list[RateCall] = []
    for item in walk(ast):
        node = item.node
        if isinstance(node, pp.Call) and node.func.name in RATE_LIKE_FUNCTIONS:
            for arg in node.args:
                if isinstance(arg, pp.MatrixSelector):
                    found.append(
                        RateCall(function=node.func.name, window=arg.range)
                    )
    return found


@dataclass(frozen=True)
class AggregationInfo:
    op: str
    by_labels: frozenset[str] | None  # None = no `by`/`without` at all
    without_labels: frozenset[str] | None


def find_aggregations(ast) -> list[AggregationInfo]:
    """Return a summary of every AggregateExpr in the tree."""
    found: list[AggregationInfo] = []
    for item in walk(ast):
        node = item.node
        if not isinstance(node, pp.AggregateExpr):
            continue
        by_labels = None
        without_labels = None
        if node.modifier is not None:
            labels = frozenset(node.modifier.labels or [])
            if node.modifier.type == pp.AggModifierType.By:
                by_labels = labels
            elif node.modifier.type == pp.AggModifierType.Without:
                without_labels = labels
        found.append(
            AggregationInfo(
                op=str(node.op),
                by_labels=by_labels,
                without_labels=without_labels,
            )
        )
    return found


def aggregation_preserves_any(agg: AggregationInfo, labels: frozenset[str]) -> bool:
    """Does this aggregation keep at least one of `labels` in its output?

    - `sum by (service) ...`       → preserves service
    - `sum without (instance) ...` → preserves everything except instance
    - `sum(...)`                   → preserves nothing (drops all)
    """
    if agg.by_labels is not None:
        return bool(agg.by_labels & labels)
    if agg.without_labels is not None:
        # `without (x)` keeps everything except x, so any identifying label
        # not in `without_labels` is preserved.
        return bool(labels - agg.without_labels)
    # No modifier → aggregates over everything → drops all labels.
    return False
