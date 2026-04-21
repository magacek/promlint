"""Load Prometheus rule YAML files and yield Rule/Group/RuleFile objects.

We use ruamel.yaml in round-trip mode because it preserves line-number metadata
on every mapping key. That's how findings get accurate file:line pointers —
without it, we'd only be able to point at filenames.

The expected schema is the standard Prometheus rule file:
    groups:
      - name: <string>
        interval: <duration?>
        rules:
          - alert: <string>
            expr: <promql>
            for: <duration?>
            labels: {...}
            annotations: {...}
          - record: <string>          # recording rule — skipped
            expr: <promql>

We silently skip recording rules (this linter is scoped to alerts) and emit
LoadWarning for anything that doesn't parse as a rule file at all.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap

from .model import Group, Rule, RuleFile


@dataclass(frozen=True)
class LoadWarning:
    file: Path
    message: str


class LoadError(Exception):
    """Raised for files that are unreadable or clearly not rule files."""


def load_rule_files(paths: Iterable[Path]) -> tuple[list[RuleFile], list[LoadWarning]]:
    yaml = YAML(typ="rt")
    rule_files: list[RuleFile] = []
    warnings: list[LoadWarning] = []

    for path in paths:
        try:
            with path.open("r", encoding="utf-8") as f:
                doc = yaml.load(f)
        except Exception as exc:
            raise LoadError(f"{path}: failed to parse YAML: {exc}") from exc

        if doc is None:
            warnings.append(LoadWarning(path, "empty file"))
            continue
        if not isinstance(doc, CommentedMap) or "groups" not in doc:
            warnings.append(
                LoadWarning(path, "no top-level `groups:` key; skipping")
            )
            continue

        groups_node = doc["groups"]
        if groups_node is None:
            continue

        groups: list[Group] = []
        for group_node in groups_node:
            group_name = group_node.get("name", "<unnamed>")
            interval = group_node.get("interval")
            rules_node = group_node.get("rules") or []

            parsed_rules: list[Rule] = []
            for rule_node in rules_node:
                rule = _parse_rule(rule_node, path, group_name)
                if rule is not None:
                    parsed_rules.append(rule)

            groups.append(
                Group(
                    name=group_name,
                    interval=interval,
                    rules=tuple(parsed_rules),
                )
            )

        rule_files.append(RuleFile(path=path, groups=tuple(groups)))

    return rule_files, warnings


def _parse_rule(node: CommentedMap, file: Path, group: str) -> Rule | None:
    """Convert a single rule mapping to a Rule, or None if it's a recording rule."""
    if "record" in node and "alert" not in node:
        return None
    if "alert" not in node:
        return None

    alert_name = node["alert"]
    expr = node.get("expr", "")
    line = _key_line(node, "alert")

    labels = dict(node.get("labels") or {})
    annotations = dict(node.get("annotations") or {})

    for_duration = node.get("for")
    keep_firing_for = node.get("keep_firing_for")

    # ruamel may return scalar types we want as plain strings
    return Rule(
        name=str(alert_name),
        expr=str(expr),
        group=group,
        file=file,
        line=line,
        for_duration=_to_str_opt(for_duration),
        keep_firing_for=_to_str_opt(keep_firing_for),
        labels={str(k): str(v) for k, v in labels.items()},
        annotations={str(k): str(v) for k, v in annotations.items()},
    )


def _key_line(node: CommentedMap, key: str) -> int:
    """Return a 1-indexed line number for the given key in a ruamel mapping."""
    try:
        return int(node.lc.key(key)[0]) + 1
    except (AttributeError, KeyError, TypeError):
        return 1


def _to_str_opt(v) -> str | None:
    if v is None:
        return None
    return str(v)
