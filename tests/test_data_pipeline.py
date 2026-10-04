"""Structural tests over the generated manifests (run after `auditbench-harbor` has produced them)."""
import json
from collections import Counter

import pytest

from auditbench_harbor.cli import GROUPS, LABELS_DIR, UNITS_DIR
from auditbench_harbor.paths import SPLITS_DIR
from auditbench_harbor.splits import check_constraints
from auditbench_harbor.windows import load_units
from training.sampler import draw_manifest, unit_probabilities

pytestmark = pytest.mark.skipif(not GROUPS.exists(), reason="manifests not generated")


def test_every_file_in_exactly_one_group_and_split():
    groups = json.load(open(GROUPS))["groups"]
    files = [f for g in groups for f in g["files"]]
    assert len(files) == len(set(files)) == 129
    assignment = {}
    for s in ("train", "dev", "test"):
        for g in json.load(open(SPLITS_DIR / f"{s}.json"))["groups"]:
            assert g["group_id"] not in assignment
            assignment[g["group_id"]] = s
    assert set(assignment) == {g["group_id"] for g in groups}
    assert check_constraints(groups, assignment, 2, 2) == []


def test_identical_contents_never_cross_splits():
    sha_split = {}
    for s in ("train", "dev", "test"):
        for g in json.load(open(SPLITS_DIR / f"{s}.json"))["groups"]:
            for f in g["files"]:
                sha_split.setdefault(f["sha256"], set()).add(s)
    assert all(len(v) == 1 for v in sha_split.values())


def test_units_follow_parent_group_split_and_ids_unique():
    units = [u for s in ("train", "dev", "test") for u in load_units(UNITS_DIR / f"{s}.jsonl")]
    ids = [u.task_id for u in units]
    assert len(ids) == len(set(ids))
    split_of = {g["group_id"]: s for s in ("train", "dev", "test") for g in json.load(open(SPLITS_DIR / f"{s}.json"))["groups"]}
    assert all(split_of[u.group_id] == u.split for u in units)
    for u in units:
        if u.label == "positive":
            assert u.supported_targets
        if u.task == "classification":
            assert u.start_line == 1 and u.n_windows == 1


def test_sampler_is_balanced_over_tasks_and_classes():
    units = load_units(UNITS_DIR / "train.jsonl")
    probs = unit_probabilities(units)
    assert abs(sum(probs.values()) - 1) < 1e-9
    draws = draw_manifest(units, 4000, seed=1)
    tasks = Counter(d.task for d in draws)
    assert all(0.2 < tasks[t] / 4000 < 0.3 for t in tasks)
    cls = Counter(d.cls for d in draws)
    assert abs(cls["positive"] / 4000 - 0.5) < 0.05
    # a group never gets more mass by having more windows: compare two negative groups of one task
    by_group = Counter()
    for u in units:
        if u.task == "lm" and u.label == "benign":
            by_group[u.group_id] += probs[u.task_id]
    assert max(by_group.values()) - min(by_group.values()) < 1e-9


def test_dev_targets_are_all_supported():
    for s in ("train", "dev"):
        for line in (LABELS_DIR / f"{s}.jsonl").read_text().splitlines():
            t = json.loads(line)
            assert t["status"] == "supported_positive", t["target_id"]
