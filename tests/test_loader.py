from pathlib import Path

from promlint.loader import load_rule_files


def test_loads_groups_and_alerting_rules(bad_rules_path: Path):
    files, warnings = load_rule_files([bad_rules_path])
    assert len(files) == 1
    assert warnings == []
    rf = files[0]
    assert len(rf.groups) == 1
    group = rf.groups[0]
    assert group.name == "bad.rules"
    # All 8 rules in bad_rules.yml are alerting rules (no recording rules)
    assert len(group.rules) == 8


def test_skips_recording_rules(good_rules_path: Path):
    files, _ = load_rule_files([good_rules_path])
    rf = files[0]
    # good_rules.yml has 3 alerting rules + 1 recording rule; loader drops the recording
    rule_names = [r.name for r in rf.alerting_rules]
    assert "WebHighErrorRate" in rule_names
    assert len(rf.alerting_rules) == 3


def test_line_numbers_point_to_alert_keyword(bad_rules_path: Path):
    files, _ = load_rule_files([bad_rules_path])
    rules = files[0].alerting_rules
    # Line numbers should be strictly increasing in file order
    lines = [r.line for r in rules]
    assert lines == sorted(lines)
    # And each > 1 (not a fallback)
    assert all(line > 1 for line in lines)

    # Grab specific rule and sanity-check line points at its `alert:` line.
    by_name = {r.name: r for r in rules}
    nfc = by_name["NoForClause"]
    contents = bad_rules_path.read_text().splitlines()
    assert "alert: NoForClause" in contents[nfc.line - 1]


def test_empty_file_emits_warning(tmp_path: Path):
    f = tmp_path / "empty.yml"
    f.write_text("")
    files, warnings = load_rule_files([f])
    assert files == []
    assert len(warnings) == 1
    assert "empty" in warnings[0].message


def test_non_rule_yaml_emits_warning(tmp_path: Path):
    f = tmp_path / "notrules.yml"
    f.write_text("some_other_schema: 1\n")
    files, warnings = load_rule_files([f])
    assert files == []
    assert len(warnings) == 1
    assert "groups" in warnings[0].message


def test_labels_and_annotations_are_strings(bad_rules_path: Path):
    files, _ = load_rule_files([bad_rules_path])
    for r in files[0].alerting_rules:
        assert all(isinstance(k, str) and isinstance(v, str) for k, v in r.labels.items())
        assert all(
            isinstance(k, str) and isinstance(v, str) for k, v in r.annotations.items()
        )
