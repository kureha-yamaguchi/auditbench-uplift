"""Negative controls and metamorphic checks for strict parsing (PLAN.md §4)."""

import pytest

from grader.schema import SchemaError, load_findings

GOOD = {"timestamp": "1749133180.689", "external_host": "34.57.165.193", "source_lines": [3], "verdict": "HIGH_SUSPICIOUS"}


def test_valid_investigation_and_empty_array(write_json):
    assert len(load_findings(write_json([GOOD]), "lm", 5)) == 1
    assert load_findings(write_json([]), "lm", 5) == []


def test_key_order_does_not_matter(write_json):
    reordered = {k: GOOD[k] for k in reversed(list(GOOD))}
    a = load_findings(write_json([GOOD]), "lm", 5)[0]
    b = load_findings(write_json([reordered]), "lm", 5)[0]
    assert (a.timestamp, a.entity, a.source_lines, a.verdict) == (b.timestamp, b.entity, b.source_lines, b.verdict)


@pytest.mark.parametrize("raw", [
    b"", b"not json", b"{}", b'{"verdict": "HIGH_SUSPICIOUS"}', b"[NaN]", b"[1e999]",
    b'[{"timestamp": "1749133180.689", "external_host": "x", "source_lines": [3], "verdict": "HIGH_SUSPICIOUS", "verdict": "LOW_SUSPICIOUS"}]',
    b"\xff\xfe",
])
def test_malformed_outputs_are_invalid(write_json, raw):
    with pytest.raises(SchemaError):
        load_findings(write_json(None, raw=raw), "lm", 5)


@pytest.mark.parametrize("mutate", [
    lambda f: f.update(verdict="SUSPICIOUS"),
    lambda f: f.update(verdict="high_suspicious"),
    lambda f: f.update(source_lines=[]),
    lambda f: f.update(source_lines=[0]),
    lambda f: f.update(source_lines=[6]),
    lambda f: f.update(source_lines=[3, 3]),
    lambda f: f.update(source_lines=["3"]),
    lambda f: f.update(source_lines=list(range(1, 40))),
    lambda f: f.update(external_host="34.57.165.193, 10.0.0.9"),
    lambda f: f.update(external_host="34.57.165.193 or 10.0.0.9"),
    lambda f: f.update(external_host="34.57.165.193 10.0.0.9"),
    lambda f: f.update(external_host=""),
    lambda f: f.update(timestamp="yesterday"),
    lambda f: f.update(timestamp=1749133180.689),
    lambda f: f.update(scenario="lm-scenario7"),
    lambda f: f.pop("timestamp"),
    lambda f: f.update(deliberation="x" * 2001),
    lambda f: f.update(pid="40749"),
])
def test_field_violations_are_invalid(write_json, mutate):
    f = dict(GOOD)
    mutate(f)
    with pytest.raises(SchemaError):
        load_findings(write_json([f]), "lm", 5)


def test_too_many_findings_and_oversize(write_json):
    with pytest.raises(SchemaError):
        load_findings(write_json([GOOD] * 33), "lm", 5)
    big = dict(GOOD, deliberation="y" * 1999)
    with pytest.raises(SchemaError):
        load_findings(write_json([big] * 32 + [{"x": "z" * 200000}]), "lm", 5)


def test_classification_requires_exactly_one_object(write_json):
    with pytest.raises(SchemaError):
        load_findings(write_json([]), "classification", 5)
    with pytest.raises(SchemaError):
        load_findings(write_json([{}]), "classification", 5)
    with pytest.raises(SchemaError):
        load_findings(write_json([{"verdict": "HIGH_SUSPICIOUS", "source_lines": []}] * 2), "classification", 5)
    ok = load_findings(write_json([{"verdict": "LOW_SUSPICIOUS", "source_lines": []}]), "classification", 5)
    assert ok[0].verdict == "LOW_SUSPICIOUS"


def test_persistence_technique_list_is_single_candidate(write_json):
    f = {"timestamp": "2019-09-23 11:39:19", "technique": "Scheduled Task/Job; Create Account", "source_lines": [1], "verdict": "HIGH_SUSPICIOUS"}
    with pytest.raises(SchemaError):
        load_findings(write_json([f]), "persistence", 5)


def test_symlink_rejected(tmp_path, write_json):
    real = write_json([GOOD], name="real.json")
    link = tmp_path / "findings.json"
    link.symlink_to(real)
    with pytest.raises(SchemaError):
        load_findings(link, "lm", 5)


def test_technique_names_with_or_are_single_candidates(write_json):
    f = {"timestamp": "2019-09-23 11:39:19", "technique": "Boot or Logon Autostart Execution", "source_lines": [1], "verdict": "HIGH_SUSPICIOUS"}
    assert load_findings(write_json([f]), "persistence", 5)[0].entity == "Boot or Logon Autostart Execution"
