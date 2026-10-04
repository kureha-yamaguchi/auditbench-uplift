"""Deterministic constrained allocation of provenance groups to train/dev/test.

Groups (not files) are the unit. Many groups serve several tasks (benign windows are shared by all
four tasks), so this is multilabel group stratification: we score candidate allocations by how far
each margin (dataset, task x label, os) is from the target fractions and keep the best feasible
candidate under a fixed seed. Hard constraints (PLAN.md §3.2): dev must contain, for every task,
at least `min_dev_groups` positive and `min_dev_groups` benign groups; train must contain at least
`min_train_positive` positive groups per task. If the requested dev fraction cannot satisfy this,
the caller walks up a ladder of dev fractions and records the deviation.
"""

from __future__ import annotations

import json
import random
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from .paths import TASKS

SPLITS = ("train", "dev", "test")


@dataclass
class Allocation:
    assignment: dict[str, str]  # group_id -> split
    fractions: tuple[float, float, float]
    seed: int
    score: float
    feasible: bool
    violations: list[str]
    candidates_tried: int


def _group_task_labels(group: dict) -> set[tuple[str, str]]:
    """(task, label) cells a group contributes to. Attack files only count for their own task."""
    cells = set()
    for task in group["tasks"]:
        cells.add((task, "attack" if group["label"] == "attack" else "benign"))
    return cells


def _margins(groups: list[dict], assignment: dict[str, str]) -> dict[str, Counter]:
    m: dict[str, Counter] = {"dataset": Counter(), "task_label": Counter(), "os": Counter(), "all": Counter()}
    for g in groups:
        s = assignment[g["group_id"]]
        m["all"][s] += 1
        m["dataset"][(g["dataset"], s)] += 1
        for cell in _group_task_labels(g):
            m["task_label"][(cell, s)] += 1
        for os_name in g["os"]:
            m["os"][(os_name, s)] += 1
    return m


def _score(groups: list[dict], assignment: dict[str, str], fractions: tuple[float, float, float]) -> float:
    """Sum of squared deviations of realised split fractions from targets, per margin cell."""
    target = dict(zip(SPLITS, fractions))
    m = _margins(groups, assignment)
    total = 0.0
    for margin in ("dataset", "task_label", "os"):
        keys = {k[0] for k in m[margin]}
        for key in keys:
            n = sum(m[margin][(key, s)] for s in SPLITS)
            for s in SPLITS:
                total += (m[margin][(key, s)] / n - target[s]) ** 2
    return total


def check_constraints(groups: list[dict], assignment: dict[str, str], min_dev_groups: int, min_train_positive: int) -> list[str]:
    m = _margins(groups, assignment)["task_label"]
    violations = []
    for task in TASKS:
        for label in ("attack", "benign"):
            if m[((task, label), "dev")] < min_dev_groups:
                violations.append(f"dev has {m[((task, label), 'dev')]} {label} groups for {task} (< {min_dev_groups})")
        if m[((task, "attack"), "train")] < min_train_positive:
            violations.append(f"train has {m[((task, 'attack'), 'train')]} attack groups for {task} (< {min_train_positive})")
    return violations


def _random_assignment(groups: list[dict], fractions: tuple[float, float, float], rng: random.Random) -> dict[str, str]:
    """Stratified random draw: within each (dataset, label, task-set) stratum, deal groups to splits
    proportionally, breaking the remainder with the seeded RNG."""
    strata: dict[tuple, list[dict]] = {}
    for g in groups:
        strata.setdefault((g["dataset"], g["label"], tuple(g["tasks"])), []).append(g)
    assignment = {}
    for members in strata.values():
        members = sorted(members, key=lambda g: g["group_id"])
        rng.shuffle(members)
        n = len(members)
        quotas = [f * n for f in fractions]
        base = [int(q) for q in quotas]
        # Leftover slots are drawn with probability proportional to the fractional quota, so small
        # strata do not systematically favour one split (deterministic rounding did).
        for _ in range(n - sum(base)):
            weights = [max(q - b, 0.0) for q, b in zip(quotas, base)]
            i = rng.choices(range(3), weights=weights if sum(weights) > 0 else fractions)[0]
            base[i] += 1
        labels = [s for s, k in zip(SPLITS, base) for _ in range(k)]
        rng.shuffle(labels)
        for g, s in zip(members, labels):
            assignment[g["group_id"]] = s
    return assignment


def allocate(groups: list[dict], fractions: tuple[float, float, float], seed: int, n_candidates: int = 4000,
             min_dev_groups: int = 2, min_train_positive: int = 2) -> Allocation:
    rng = random.Random(seed)
    best: Allocation | None = None
    for i in range(n_candidates):
        assignment = _random_assignment(groups, fractions, rng)
        violations = check_constraints(groups, assignment, min_dev_groups, min_train_positive)
        feasible = not violations
        score = _score(groups, assignment, fractions)
        key = (0 if feasible else 1, len(violations), score)
        if best is None or key < (0 if best.feasible else 1, len(best.violations), best.score):
            best = Allocation(assignment, fractions, seed, score, feasible, violations, i + 1)
    assert best is not None
    best.candidates_tried = n_candidates
    return best


def allocate_with_ladder(groups: list[dict], ladder: list[tuple[float, float, float]], seed: int, **kw) -> tuple[Allocation, list[dict]]:
    """Try each fraction triple in order; return the first feasible allocation and the attempt log."""
    attempts = []
    for fractions in ladder:
        alloc = allocate(groups, fractions, seed, **kw)
        attempts.append({"fractions": fractions, "feasible": alloc.feasible, "violations": alloc.violations, "score": alloc.score})
        if alloc.feasible:
            return alloc, attempts
    return alloc, attempts  # last (infeasible) allocation; caller must report


def split_counts(groups: list[dict], assignment: dict[str, str]) -> dict:
    m = _margins(groups, assignment)
    cells = {}
    for (cell, s), n in sorted(m["task_label"].items()):
        cells.setdefault(f"{cell[0]}/{cell[1]}", {})[s] = n
    return {
        "groups": {s: m["all"][s] for s in SPLITS},
        "dataset": {f"{d}/{s}": n for (d, s), n in sorted(m["dataset"].items())},
        "task_label": cells,
        "os": {f"{o}/{s}": n for (o, s), n in sorted(m["os"].items())},
    }


def write_split_files(groups: list[dict], records_by_path: dict, assignment: dict[str, str], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for s in SPLITS:
        members = [g for g in groups if assignment[g["group_id"]] == s]
        payload = {
            "split": s,
            "groups": [
                {
                    **{k: g[k] for k in ("group_id", "dataset", "label", "os", "hosts", "tasks", "scenario_keys")},
                    "files": [{"rel_path": p, "sha256": records_by_path[p].sha256, "task": records_by_path[p].task,
                               "representation": records_by_path[p].representation, "lines": records_by_path[p].lines}
                              for p in g["files"]],
                }
                for g in members
            ],
        }
        (out_dir / f"{s}.json").write_text(json.dumps(payload, indent=1) + "\n")
