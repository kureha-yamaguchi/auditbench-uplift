"""Canonical task units: consecutive line windows for investigation, whole files for classification.

Each unit gets an opaque, manifest-derived id. Positive/negative status comes from the private
target manifest: a window is positive for a target when at least one of the target's evidence lines
in that view lies inside the window.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import SCHEMA_VERSION
from .inventory import FileRecord
from .labels import Target

WINDOW_LINES = {"edge": 400, "raw": 1000}


@dataclass
class TaskUnit:
    task_id: str
    rel_path: str
    file_sha256: str
    dataset: str
    task: str
    representation: str
    os: str
    scenario_key: str
    group_id: str
    split: str
    start_line: int   # 1-based inclusive
    end_line: int     # 1-based inclusive
    n_lines: int
    window_index: int
    n_windows: int
    label: str        # positive | negative_attack_file | benign | attack (classification) | quarantined
    supported_targets: list[str] = field(default_factory=list)
    ambiguous_targets: list[str] = field(default_factory=list)
    quarantine_reason: str = ""


def _task_id(file_sha: str, task: str, rep: str, start: int, end: int) -> str:
    raw = f"{SCHEMA_VERSION}|{file_sha}|{task}|{rep}|{start}-{end}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def build_units(records: list[FileRecord], targets: list[Target], group_of: dict[str, str], split_of: dict[str, str]) -> list[TaskUnit]:
    targets_by_file: dict[str, list[Target]] = {}
    for t in targets:
        for rel_path in t.evidence:
            targets_by_file.setdefault(rel_path, []).append(t)

    units: list[TaskUnit] = []
    for r in records:
        gid = group_of[r.rel_path]
        split = split_of[gid]
        if r.task == "classification":
            units.append(TaskUnit(_task_id(r.sha256, r.task, r.representation, 1, r.lines), r.rel_path, r.sha256,
                                  r.dataset, r.task, r.representation, r.os, r.scenario_key, gid, split,
                                  1, r.lines, r.lines, 0, 1, "attack" if r.label == "attack" else "benign"))
            continue
        size = WINDOW_LINES[r.representation]
        n_windows = -(-r.lines // size)
        file_targets = targets_by_file.get(r.rel_path, [])
        for w in range(n_windows):
            start, end = w * size + 1, min((w + 1) * size, r.lines)
            supported, ambiguous = [], []
            for t in file_targets:
                if any(start <= ln <= end for ln in t.evidence.get(r.rel_path, [])):
                    (supported if t.status == "supported_positive" else ambiguous).append(t.target_id)
            if r.label == "benign":
                label = "benign"
            elif supported:
                label = "positive"
            elif ambiguous:
                label, reason = "quarantined", "window contains only ambiguous-target evidence"
            else:
                label = "negative_attack_file"
            unit = TaskUnit(_task_id(r.sha256, r.task, r.representation, start, end), r.rel_path, r.sha256, r.dataset,
                            r.task, r.representation, r.os, r.scenario_key, gid, split, start, end, end - start + 1,
                            w, n_windows, label, sorted(supported), sorted(ambiguous))
            if label == "quarantined":
                unit.quarantine_reason = reason
            units.append(unit)
    ids = [u.task_id for u in units]
    assert len(ids) == len(set(ids)), "task id collision"
    return units


def write_units(units: list[TaskUnit], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as fh:
        for u in units:
            fh.write(json.dumps(asdict(u)) + "\n")


def load_units(path: Path) -> list[TaskUnit]:
    return [TaskUnit(**json.loads(line)) for line in path.read_text().splitlines() if line.strip()]


def summarize_units(units: list[TaskUnit]) -> dict:
    from collections import Counter

    c = Counter((u.split, u.task, u.label) for u in units)
    out: dict = {}
    for (split, task, label), n in sorted(c.items()):
        out.setdefault(split, {}).setdefault(task, {})[label] = n
    groups = Counter((u.split, u.task, u.label, u.group_id) for u in units)
    indep = Counter()
    for (split, task, label, _g) in groups:
        indep[(split, task, label)] += 1
    out["independent_groups"] = {f"{s}/{t}/{label}": n for (s, t, label), n in sorted(indep.items())}
    return out
