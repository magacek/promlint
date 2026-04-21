"""Render Findings as human-readable text or JSON.

The text format is tuned for terminal review: group by file, color severity,
show the rule name and check ID on one line, then the message and suggestion
indented below. The JSON format is a flat list of finding objects — easy for
CI to parse, stable schema documented in the README.
"""

from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import TextIO

from colorama import Fore, Style, init as colorama_init

from .model import Finding, Severity


_SEVERITY_COLOR = {
    Severity.ERROR: Fore.RED,
    Severity.WARNING: Fore.YELLOW,
    Severity.INFO: Fore.CYAN,
}

_SEVERITY_LABEL = {
    Severity.ERROR: "ERROR",
    Severity.WARNING: "WARN ",
    Severity.INFO: "INFO ",
}


class TextReporter:
    def __init__(self, *, color: bool | None = None, stream: TextIO | None = None):
        self.stream = stream if stream is not None else sys.stdout
        # Detect TTY unless color is forced.
        if color is None:
            color = self.stream.isatty()
        self.color = color
        if color:
            colorama_init(strip=False)

    def write(self, findings: list[Finding], *, scanned_files: int) -> None:
        if not findings:
            self._line(
                f"{scanned_files} file(s) scanned, no findings."
            )
            return

        by_file: dict[Path, list[Finding]] = defaultdict(list)
        for f in findings:
            by_file[f.file].append(f)

        for path in sorted(by_file):
            self._line(str(path))
            file_findings = sorted(
                by_file[path], key=lambda f: (f.line, f.check_id)
            )
            for f in file_findings:
                self._render_finding(f)
            self._line("")

        counts = Counter(f.severity for f in findings)
        summary_bits = [
            f"{counts[sev]} {sev.value}"
            for sev in (Severity.ERROR, Severity.WARNING, Severity.INFO)
            if counts[sev]
        ]
        self._line(
            f"{scanned_files} file(s) scanned, {len(findings)} finding(s) "
            f"({', '.join(summary_bits)})"
        )

    def _render_finding(self, f: Finding) -> None:
        label = _SEVERITY_LABEL[f.severity]
        if self.color:
            label = f"{_SEVERITY_COLOR[f.severity]}{label}{Style.RESET_ALL}"
        head = (
            f"  {label}  {f.file}:{f.line}  "
            f"{f.rule_name}  [{f.check_id}]"
        )
        self._line(head)
        self._line(f"         {f.message}")
        if f.suggestion:
            arrow = "→"
            self._line(f"         {arrow} {f.suggestion}")

    def _line(self, s: str) -> None:
        print(s, file=self.stream)


class JsonReporter:
    def __init__(self, *, stream: TextIO | None = None):
        self.stream = stream if stream is not None else sys.stdout

    def write(self, findings: list[Finding], *, scanned_files: int) -> None:
        payload = {
            "scanned_files": scanned_files,
            "finding_count": len(findings),
            "findings": [f.to_dict() for f in findings],
        }
        json.dump(payload, self.stream, indent=2, sort_keys=True)
        self.stream.write("\n")
