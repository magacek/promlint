"""CLI entry point: parse args, load files, run enabled checks, render.

Exit codes:
    0   no findings at or above the `--fail-on` severity threshold
    1   findings at or above the threshold
    2   invalid usage (bad flags, unreadable file, etc.) — argparse / argparse-like
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from pathlib import Path
from typing import Iterable

from .checks import ALL_CHECKS
from .config import Config, load_config
from .loader import LoadError, load_rule_files
from .model import Finding, Severity
from .report import JsonReporter, TextReporter


def _expand_paths(paths: list[str]) -> list[Path]:
    """Accept files, directories, or globs; return a de-duplicated file list.

    Directories are walked recursively for `*.yml` and `*.yaml`. Individual
    files are taken as-is (even if the extension is different) so someone
    pointing at a specific file always wins.
    """
    out: list[Path] = []
    seen: set[Path] = set()
    for raw in paths:
        p = Path(raw)
        if p.is_dir():
            for ext in ("*.yml", "*.yaml"):
                for f in sorted(p.rglob(ext)):
                    if f not in seen:
                        seen.add(f)
                        out.append(f)
        elif p.exists():
            if p not in seen:
                seen.add(p)
                out.append(p)
        else:
            # Let the caller see the missing path explicitly.
            raise LoadError(f"path does not exist: {p}")
    return out


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="promlint",
        description=(
            "Lint Prometheus alerting rule YAML files for common quality "
            "issues and anti-patterns."
        ),
    )
    p.add_argument(
        "paths",
        nargs="*",
        help="Rule files or directories to scan (directories are walked for *.yml/*.yaml).",
    )
    p.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        help="Output format (default: text).",
    )
    p.add_argument(
        "--fail-on",
        choices=[s.value for s in Severity],
        default=None,
        help="Exit non-zero if any finding has this severity or higher (default: error).",
    )
    p.add_argument(
        "--disable",
        default="",
        help="Comma-separated list of check IDs to skip.",
    )
    p.add_argument(
        "--enable",
        default="",
        help="Comma-separated list of check IDs to run exclusively (overrides --disable).",
    )
    p.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Path to a YAML config file (overrides defaults, overridden by CLI flags).",
    )
    p.add_argument(
        "--list-checks",
        action="store_true",
        help="Print the available check IDs and exit.",
    )
    p.add_argument(
        "--no-color",
        action="store_true",
        help="Disable ANSI color in text output.",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.list_checks:
        for check in ALL_CHECKS:
            print(f"{check.id:45} {check.description}")
        return 0

    if not args.paths:
        parser.error("at least one path is required (file or directory)")

    # Build config: file first, then CLI overrides.
    try:
        config = load_config(args.config)
    except Exception as exc:
        print(f"error loading config: {exc}", file=sys.stderr)
        return 2

    # CLI --fail-on overrides config
    if args.fail_on:
        config = replace(config, fail_on=Severity.from_str(args.fail_on))

    # --disable merges with config; --enable replaces entirely
    cli_disabled = {s.strip() for s in args.disable.split(",") if s.strip()}
    cli_enabled = {s.strip() for s in args.enable.split(",") if s.strip()}

    all_ids = {c.id for c in ALL_CHECKS}
    unknown = (cli_disabled | cli_enabled) - all_ids
    if unknown:
        print(
            f"error: unknown check id(s): {', '.join(sorted(unknown))}. "
            f"Run `promlint --list-checks` for the valid set.",
            file=sys.stderr,
        )
        return 2

    if cli_enabled:
        active_checks = [c for c in ALL_CHECKS if c.id in cli_enabled]
    else:
        disabled = config.disabled_checks | cli_disabled
        active_checks = [c for c in ALL_CHECKS if c.id not in disabled]

    # Resolve paths
    try:
        files = _expand_paths(args.paths)
    except LoadError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if not files:
        print("no YAML rule files found in the given paths", file=sys.stderr)
        return 2

    # Load rule files
    try:
        rule_files, warnings = load_rule_files(files)
    except LoadError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    for w in warnings:
        print(f"warning: {w.file}: {w.message}", file=sys.stderr)

    # Run checks
    findings: list[Finding] = []
    for check in active_checks:
        findings.extend(check.run(rule_files, config))

    # Sort: by file, then line, then severity (error first), then check_id
    findings.sort(
        key=lambda f: (str(f.file), f.line, -f.severity.rank, f.check_id)
    )

    # Render
    if args.format == "json":
        reporter = JsonReporter()
    else:
        reporter = TextReporter(color=False if args.no_color else None)
    reporter.write(findings, scanned_files=len(rule_files))

    # Exit code
    threshold = config.fail_on
    if any(f.severity.rank >= threshold.rank for f in findings):
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
