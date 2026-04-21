# promlint

A CLI that statically analyzes Prometheus alerting rule YAML files and flags
common quality issues and anti-patterns — the kinds of things that make alerts
noisy, unreliable, or hard to act on during an incident.

```
$ promlint tests/fixtures/bad_rules.yml
tests/fixtures/bad_rules.yml
  WARN   tests/fixtures/bad_rules.yml:9  NoForClause  [missing-for]
         Alert has no `for:` clause; it will fire on the first scrape where
         the expression is true, which is almost always noisier than intended.
         → Add `for: 5m` (or similar) so the condition must hold before paging.

  ERROR  tests/fixtures/bad_rules.yml:46  CounterBareCompare  [counter-without-rate]
         `http_requests_total` looks like a counter but is not wrapped in
         rate/increase/irate. Counters only grow and reset on restart, so
         direct comparisons fire indefinitely or not at all.
         → Use e.g. `rate(http_requests_total[5m])`.

  ... (7 more)

1 file(s) scanned, 9 finding(s) (3 error, 6 warning)
$ echo $?
1
```

---

## Quick start

```bash
# Install
uv venv --python 3.12            # or python3 -m venv .venv
source .venv/bin/activate
uv pip install -e ".[dev]"        # or: pip install -e ".[dev]"

# Run
promlint tests/fixtures/bad_rules.yml              # text output, exits 1 on findings
promlint --format json tests/fixtures/             # JSON, recurses directories
promlint --disable missing-for tests/fixtures/     # skip a check
promlint --list-checks                             # enumerate checks

# Tests
pytest
```

---

## The 7 checks

Each check addresses one of the four categories the assignment calls out.
Every finding carries a `message` explaining the problem and a `suggestion`
describing the usual fix.

| ID | Severity | Category | What it catches |
|---|---|---|---|
| `missing-for` | warning | Aggressive firing | Alert with no `for:` clause |
| `missing-annotations` | error / warning | Missing metadata | No `summary`/`description` (error); no `runbook_url` (warning) |
| `missing-severity-label` | error | Missing metadata | No `severity` label, or an unrecognized value |
| `short-rate-window` | warning | Aggressive firing | `rate()`/`increase()` with a window < 2m, or `for:` < rate window |
| `counter-without-rate` | error | Wrong selector | Counter-named metric (`*_total`) compared directly instead of via `rate()` |
| `aggregation-drops-identifying-labels` | warning | Too-broad selector | Aggregation with no `by (...)` preserving `service`/`instance`/`job`/etc. |
| `duplicate-alert-expression` | warning | Relationships between alerts | Two alerts share a normalized expression (detects both exact duplicates and undocumented severity ladders) |

### Why each check exists (the 3am-page argument)

- **missing-for** — A rule without `for:` fires on a single scrape. One missed
  scrape, one transient spike, and on-call gets paged. Forcing an explicit
  `for:` makes "how long must this be true?" a design decision, not an
  accident. `for: 0s` is allowed so discrete events (deploy-failed,
  backup-script-exited) can opt in.

- **missing-annotations** — An alert name plus nothing else is useless at 3am.
  `summary` and `description` carry the why-does-this-matter; `runbook_url` is
  a pointer to mitigation steps. Treated as two tiers so teams without formal
  runbooks can drop the warning via config.

- **missing-severity-label** — Alertmanager routes on `severity`. Missing or
  typo'd labels (`severity: critcal`) get silently dropped to the catch-all
  receiver. This is almost always a bug.

- **short-rate-window** — `rate(m[1m])` with a 30s scrape interval has two
  samples; one missed scrape produces a wildly wrong rate. The conventional
  guidance is ≥4× the scrape interval. We default to a 2m minimum, tunable.
  The check also flags `for:` < the longest rate window: `for: 1m` on
  `rate(m[5m])` means the alert can fire before the rate window has filled
  with post-event data.

- **counter-without-rate** — Prometheus counters (`*_total` by convention)
  only grow, and reset on restart. `http_requests_total > 1000` is almost
  always a bug: on a freshly-restarted process the counter is 0; elsewhere
  it crossed 1000 days ago and is permanently "alerting". This is the most
  reliable static finding of all of them — the naming convention is a strong
  signal.

- **aggregation-drops-identifying-labels** — `sum(rate(errors_total[5m])) > 100`
  fires one alert when fleet-wide errors exceed 100. On-call sees "errors are
  high" and has no idea which service, pod, or instance. This check needs
  AST access — regex can't cleanly tell `sum by (job)` from `sum(job)` (a
  count) from `sum without (instance)`.

- **duplicate-alert-expression** — Two rules with the same normalized
  expression are either a copy-paste bug (same severity → both page at once)
  or a severity ladder (different severities → warning and critical
  thresholds on the same signal). The check detects both and emits the
  appropriate message, so an undocumented ladder becomes visible without
  being treated as a bug.

---

## Key design decisions & tradeoffs

### 1. Real PromQL AST parser, not regex

Three of the seven checks (`counter-without-rate`, `short-rate-window`,
`aggregation-drops-identifying-labels`) need to reason about PromQL semantics.
I used `promql-parser`, a PyO3 binding around the Rust PromQL parser from
the Prometheus community, and wrote a small visitor in
[`promql.py`](src/promlint/promql.py) that walks the AST with an
`inside_rate` context flag.

**Why not regex:** a regex for "metric named `*_total` compared without a rate
wrapper" is easy to get wrong — `http_errors_total_ratio` is not a counter,
`rate(http_requests_total[5m]) > rate(http_requests_total[1m])` has two
rate-wrapped uses, and `sum(http_requests_total)` is not a direct comparison.
The AST makes these distinctions cheap.

**Tradeoff:** one external dependency, and the binding wraps a Rust parser
we don't control. If the binding broke or became unavailable on a target
platform, the fallback plan is a minimal `pyparsing` grammar covering
aggregations, function calls, matchers, and range vectors — enough for the
three AST-based checks. Documented here so a reader knows what I'd do.

### 2. `ruamel.yaml` over PyYAML for line numbers

Findings are only useful if they point at a line. PyYAML loses source
positions unless you go through an `add_constructor` workaround. ruamel.yaml
preserves `.lc.key('alert')[0]` on every mapping key out of the box, which
lets [`loader.py`](src/promlint/loader.py) attribute every finding to the
`alert:` line that defines the rule. Worth the extra dependency.

### 3. Severity is configurable per-check

[`config.py`](src/promlint/config.py) lets a user override severity on any
check. Teams legitimately disagree on whether a missing `runbook_url` is an
error or a warning. Making it configurable keeps the tool adoptable. The
default severities reflect my opinion about what's most likely a bug vs.
most likely a stylistic miss.

### 4. Check registry pattern

Each check lives in its own file under [`src/promlint/checks/`](src/promlint/checks/)
and is registered in `ALL_CHECKS` in
[`checks/__init__.py`](src/promlint/checks/__init__.py). Adding a new check
is one file plus one line. This is deliberate preparation for the follow-up
interview's "extend with a small new feature" step.

### 5. Cross-rule check is separate from single-rule checks

Six checks iterate `for rule in rule_files.alerting_rules`. The seventh
(`duplicate-alert-expression`) needs the full corpus. I kept them on the
same `Check` ABC with a `run(rule_files, config) -> list[Finding]` signature
— the cross-rule case fits that shape fine, and a separate class hierarchy
would be ceremony without payoff.

### 6. Two-tier reporting (required vs recommended)

`missing-annotations` emits two findings for a truly bare rule: an ERROR
for the required set (`summary`, `description`) and a WARNING for the
recommended set (`runbook_url`). This matters because the fix-cost is
different: writing a summary is mandatory; writing a runbook is aspirational.
Teams without runbooks can drop the warning via `recommended_annotations: []`.

### 7. Ladder detection in duplicate check

Two rules with the same expression but **different** `severity` labels are
almost certainly a severity ladder ("warn at 80%, page at 95%"). I emit a
softer message for that case asking the author to verify threshold/for
differ, rather than calling it a bug. Reduces false-positive fatigue on a
legitimate pattern.

### 8. Explicit non-goals

- **Recording rules** are skipped silently (detected by `record:` key vs
  `alert:` key). The assignment is scoped to alerts; checking recording
  rules would be a separate tool.
- **Live Prometheus validation** (label cardinality, metric existence) is
  out of scope — this is a pure static analyzer.
- **Auto-fix (`--fix`)** would be nice but isn't worth the complexity for a
  take-home.
- **SARIF output** would enable GitHub code-scanning integration, but it's
  not a realistic requirement for a first version.

### Checks I considered and rejected

- **`for:` too long (> 1h)** — legitimately used for SLO burn-rate alerts
  and long-cooldown conditions. Too opinionated to flag.
- **Label cardinality explosion** — requires metric samples, not just the
  rule file. Out of scope.
- **Rule-naming conventions (CamelCase, etc.)** — bikeshed territory. A
  team that cares can wire a linter for this elsewhere.
- **Missing Alertmanager routes for a given severity** — that lives in the
  Alertmanager config, not the rule file.

---

## Architecture

```
src/promlint/
├── cli.py              # argparse entry point, path expansion, orchestration
├── model.py            # Severity enum; Rule / Group / RuleFile / Finding dataclasses
├── loader.py           # ruamel.yaml loading, line-number preservation
├── promql.py           # AST helpers on top of promql-parser
├── config.py           # Config dataclass, YAML config file loading
├── report.py           # TextReporter (terminal) + JsonReporter (CI)
└── checks/
    ├── base.py                              # Check ABC
    ├── missing_for.py
    ├── missing_annotations.py
    ├── missing_severity_label.py
    ├── short_rate_window.py
    ├── counter_without_rate.py
    ├── aggregation_labels.py
    ├── duplicate_expression.py
    └── __init__.py                          # ALL_CHECKS registry

tests/
├── fixtures/
│   ├── good_rules.yml     # passes every check; regression canary
│   ├── bad_rules.yml      # one rule per check, designed to trigger it
│   └── realistic.yml      # kube-prometheus-style rules with seeded issues
├── test_loader.py
├── test_promql.py
├── test_checks.py         # per-check unit tests + end-to-end on fixtures
├── test_report.py         # text + JSON formatting
└── test_cli.py            # subprocess integration; exit codes, flag handling
```

57 tests cover loader, AST helpers, every check, both reporters, and the
CLI end-to-end. `pytest -q` runs in under a second.

---

## Configuration file

A YAML config file can override defaults. Pass with `--config path.yml`.

```yaml
# promlint.yml
disabled_checks: [short-rate-window]

required_annotations: [summary, description, owner]
recommended_annotations: []   # drop the runbook_url warning

valid_severity_values: [critical, warning, info, page]

min_rate_window: 3m

# Make missing-annotations a warning instead of an error.
severity_overrides:
  missing-annotations: warning

fail_on: warning
```

---

## CLI surface

```
promlint [paths ...]                         # scan one or more files/dirs
promlint --format {text,json}                # output format (default: text)
promlint --fail-on {error,warning,info}      # exit non-zero at/above this
promlint --disable <id>,<id>                 # skip named checks
promlint --enable  <id>,<id>                 # run ONLY these checks
promlint --config path.yml                   # load overrides from a config file
promlint --no-color                          # disable ANSI color
promlint --list-checks                       # print check IDs and descriptions
```

Exit codes: `0` clean (or findings below threshold), `1` findings at or above
`--fail-on` (default: error), `2` invalid usage.

---

## What I'd add next

Ordered roughly by value:

1. **`metric-name-does-not-exist`** — shells out to a running Prometheus or
   reads a metric list from a file; warns on metrics the cluster doesn't
   emit. The #1 class of silently-broken alert in my experience.
2. **`template-interpolation-uses-undefined-label`** — parses
   `{{ $labels.foo }}` in annotations and checks whether the expression's
   output has that label. Catches typos like `{{ $labels.servic }}` that
   render as literal text in PagerDuty.
3. **Auto-fix for the safe checks** — `--fix` could add a default `for:`
   block or wrap a bare counter in `rate()`, guarded by `git diff` preview.
4. **SARIF output** for GitHub code scanning.
5. **Incremental mode** — only lint rules that changed relative to a base
   branch, for PR-scoped CI.
6. **`for` too long with `keep_firing_for` pattern** — warn about stale
   alerts that linger past their signal because of a huge `for:` combined
   with `keep_firing_for`.
