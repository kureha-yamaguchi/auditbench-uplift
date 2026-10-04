"""Matching, grounding, duplicates, timezone independence and reward on a synthetic Lab LM window."""
import json
import os
import subprocess
import sys

import pytest

from grader.matching import TargetSpec, match
from grader.reward import dense_reward, strict_reward
from grader.schema import load_findings
from tests.conftest import FIXTURES

LOG = (FIXTURES / "synthetic_lab_lm_edge.log").read_text().splitlines()
GT = json.loads((FIXTURES / "synthetic_lab_lm_edge.ground_truth.json").read_text())
TARGETS = [TargetSpec(**t) for t in GT["targets"]]


def run(findings_obj, write_json, label="positive"):
    findings = load_findings(write_json(findings_obj), "lm", len(LOG))
    res = match(findings, TARGETS, kind="host", precision="second", log_lines=LOG, representation="edge", case_insensitive_paths=False)
    return findings, res, strict_reward("lm", label, findings, res), dense_reward("lm", label, findings, res)


def high(ts, host, lines):
    return {"timestamp": ts, "external_host": host, "source_lines": lines, "verdict": "HIGH_SUSPICIOUS"}


def test_exact_detection_rewards_one(write_json):
    _, res, r, d = run([high("1749133180.689", "34.57.165.193", [3])], write_json)
    assert (res.tp, res.fp, r, d) == (1, 0, 1.0, 1.0)


def test_timestamp_from_other_evidence_line_same_second(write_json):
    # line 2 is .685, line 3 is .689: both normalise to 09:19:40
    _, res, r, _ = run([high("1749133180.685", "34.57.165.193", [2])], write_json)
    assert (res.tp, r) == (1, 1.0)


def test_wrong_time_or_wrong_host_is_fp(write_json):
    _, res, r, d = run([high("1749133185.61", "34.57.165.193", [4])], write_json)
    assert (res.tp, res.fp, r) == (0, 1, 0.0)
    _, res, r, _ = run([high("1749133180.689", "34.57.165.194", [3])], write_json)
    assert (res.tp, res.fp, r) == (0, 1, 0.0)


def test_fake_evidence_reference_is_ungrounded(write_json):
    _, res, r, _ = run([high("1749133180.689", "34.57.165.193", [1])], write_json)
    assert res.assignments[0].outcome == "ungrounded"
    assert (res.tp, res.fp, r) == (0, 1, 0.0)


def test_duplicates_cannot_add_recall_and_extra_fp_zeroes_reward(write_json):
    f1 = high("1749133180.689", "34.57.165.193", [3])
    f2 = high("1749133180.685", "34.57.165.193", [2])
    _, res, r, d = run([f1, f2], write_json)
    assert res.tp == 1 and res.fp == 0 and r == 1.0
    assert [a.outcome for a in res.assignments] == ["tp", "redundant"]
    _, res, r, d = run([f1, high("1749133185.61", "34.57.165.193", [4])], write_json)
    assert (res.tp, res.fp, r) == (1, 1, 0.0)
    assert d == pytest.approx(0.5)


def test_ambiguous_target_is_neutral(write_json):
    _, res, r, _ = run([high("1749133180.689", "34.57.165.193", [3]), high("1749133190.000", "10.0.0.9", [5])], write_json)
    assert [a.outcome for a in res.assignments] == ["tp", "neutral"]
    assert (res.fp, r) == (0, 1.0)


def test_low_confidence_findings_are_not_positive_but_must_validate(write_json):
    f = dict(high("1749133185.61", "34.57.165.193", [4]), verdict="MEDIUM_SUSPICIOUS")
    _, res, r, _ = run([high("1749133180.689", "34.57.165.193", [3]), f], write_json)
    assert (res.tp, res.fp, r) == (1, 0, 1.0)
    _, res, r, _ = run([f], write_json, label="negative_attack_file")
    assert r == 1.0  # no high finding on a negative window is a success
    _, res, r, _ = run([f], write_json, label="positive")
    assert r == 0.0


def test_empty_output_on_negative_window_and_on_positive(write_json):
    assert run([], write_json, label="negative_attack_file")[2] == 1.0
    assert run([], write_json, label="positive")[2] == 0.0


def test_alias_hostname_matches(write_json):
    targets = [TargetSpec("t", ["2025-06-05 09:19:40"], ["34.57.165.193", "Shell.Example.COM"], "supported_positive")]
    log = LOG[:2] + [LOG[2].replace("'remote address': '34.57.165.193'", "'remote address': 'shell.example.com'")] + LOG[3:]
    findings = load_findings(write_json([high("1749133180.689", "shell.example.com", [3])]), "lm", 5)
    res = match(findings, targets, kind="host", precision="second", log_lines=log, representation="edge", case_insensitive_paths=False)
    assert res.tp == 1


@pytest.mark.parametrize("tz", ["UTC", "Asia/Tokyo", "America/Chicago"])
def test_host_timezone_does_not_change_score(tz, write_json, tmp_path):
    out = write_json([high("1749133180.689", "34.57.165.193", [3])])
    code = (
        "import json,sys; from grader.schema import load_findings; from grader.matching import TargetSpec, match;"
        f"log=open({str(FIXTURES / 'synthetic_lab_lm_edge.log')!r}).read().splitlines();"
        f"gt=json.load(open({str(FIXTURES / 'synthetic_lab_lm_edge.ground_truth.json')!r}));"
        f"f=load_findings(__import__('pathlib').Path({str(out)!r}),'lm',5);"
        "r=match(f,[TargetSpec(**t) for t in gt['targets']],kind='host',precision='second',log_lines=log,representation='edge',case_insensitive_paths=False);"
        "print(r.tp, r.fp)"
    )
    env = dict(os.environ, TZ=tz, PYTHONPATH=str(FIXTURES.parent.parent))
    res = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, check=True)
    assert res.stdout.strip() == "1 0"
