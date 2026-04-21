"""Check registry. Adding a new check means: create the module, import it here,
add it to ALL_CHECKS. The CLI's --disable flag filters against the `id` attr.
"""

from __future__ import annotations

from .aggregation_labels import AggregationDropsLabelsCheck
from .base import Check
from .counter_without_rate import CounterWithoutRateCheck
from .duplicate_expression import DuplicateExpressionCheck
from .missing_annotations import MissingAnnotationsCheck
from .missing_for import MissingForCheck
from .missing_severity_label import MissingSeverityLabelCheck
from .short_rate_window import ShortRateWindowCheck

ALL_CHECKS: list[Check] = [
    MissingForCheck(),
    MissingAnnotationsCheck(),
    MissingSeverityLabelCheck(),
    ShortRateWindowCheck(),
    CounterWithoutRateCheck(),
    AggregationDropsLabelsCheck(),
    DuplicateExpressionCheck(),
]

__all__ = ["ALL_CHECKS", "Check"]
