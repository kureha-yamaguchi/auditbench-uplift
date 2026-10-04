"""Explicit balanced training sampler (PLAN.md §3.5).

Hierarchy per draw:
  1. task uniformly over the four tasks;
  2. class (positive/attack vs negative/benign) with probability 1/2;
  3. within the negative class, negative-attack-file windows vs benign-file windows 1/2 where both exist;
  4. scenario group uniformly among eligible groups; 5. representation uniformly; 6. a canonical unit uniformly.

The output is an auditable *sampling manifest*: an i.i.d. sequence of (task_id, probability) of
length iterations x batch. The trainer consumes it as a materialised dataset directory of unique
symlinks; because the sequence is i.i.d., any shuffle the trainer applies preserves the marginal
distribution. Exposure per group and realised frequencies are reported alongside.
"""

from __future__ import annotations

import json
import random
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

from auditbench_harbor.paths import TASKS
from auditbench_harbor.windows import TaskUnit

POSITIVE = {"positive", "attack"}
NEGATIVE_KINDS = ("negative_attack_file", "benign")


@dataclass
class Draw:
    index: int
    task_id: str
    task: str
    cls: str
    kind: str
    group_id: str
    representation: str
    probability: float


def _tree(units: list[TaskUnit]) -> dict:
    """task -> class -> kind -> group -> representation -> [units]"""
    tree: dict = defaultdict(lambda: defaultdict(lambda: defaultdict(lambda: defaultdict(lambda: defaultdict(list)))))
    for u in units:
        if u.label == "quarantined":
            continue
        cls = "positive" if u.label in POSITIVE else "negative"
        kind = u.label if cls == "negative" else "positive"
        tree[u.task][cls][kind][u.group_id][u.representation].append(u)
    return tree


def unit_probabilities(units: list[TaskUnit]) -> dict[str, float]:
    """Marginal probability of every unit under the hierarchy (sums to 1 over all eligible units)."""
    tree = _tree(units)
    probs: dict[str, float] = {}
    tasks_present = [t for t in TASKS if t in tree]
    for task in tasks_present:
        p_task = 1 / len(tasks_present)
        classes = [c for c in ("positive", "negative") if tree[task].get(c)]
        for cls in classes:
            p_cls = p_task / len(classes)
            kinds = list(tree[task][cls])
            for kind in kinds:
                p_kind = p_cls / len(kinds)
                groups = tree[task][cls][kind]
                for g, reps in groups.items():
                    p_group = p_kind / len(groups)
                    for rep, members in reps.items():
                        p_rep = p_group / len(reps)
                        for u in members:
                            probs[u.task_id] = p_rep / len(members)
    return probs


def missing_strata(units: list[TaskUnit]) -> list[str]:
    tree = _tree(units)
    out = []
    for task in TASKS:
        for cls in ("positive", "negative"):
            if not tree.get(task, {}).get(cls):
                out.append(f"{task}/{cls}")
    return out


def draw_manifest(units: list[TaskUnit], n_draws: int, seed: int) -> list[Draw]:
    rng = random.Random(seed)
    by_id = {u.task_id: u for u in units}
    probs = unit_probabilities(units)
    ids = sorted(probs)
    weights = [probs[i] for i in ids]
    draws = []
    for i, tid in enumerate(rng.choices(ids, weights=weights, k=n_draws)):
        u = by_id[tid]
        cls = "positive" if u.label in POSITIVE else "negative"
        draws.append(Draw(i, tid, u.task, cls, u.label, u.group_id, u.representation, probs[tid]))
    return draws


def exposure_report(draws: list[Draw], units: list[TaskUnit]) -> dict:
    n = len(draws)
    by_task = Counter(d.task for d in draws)
    by_task_cls = Counter((d.task, d.cls) for d in draws)
    by_group = Counter(d.group_id for d in draws)
    eligible_groups = {u.group_id for u in units if u.label != "quarantined"}
    return {
        "n_draws": n,
        "task_frequency": {t: by_task[t] / n for t in TASKS},
        "task_class_frequency": {f"{t}/{c}": v / n for (t, c), v in sorted(by_task_cls.items())},
        "distinct_units": len({d.task_id for d in draws}),
        "distinct_groups": len(by_group),
        "groups_never_drawn": sorted(eligible_groups - set(by_group)),
        "group_exposure": dict(sorted(by_group.items())),
        "missing_strata": missing_strata(units),
    }


def write_manifest(draws: list[Draw], path: Path, meta: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as fh:
        fh.write(json.dumps({"meta": meta}) + "\n")
        for d in draws:
            fh.write(json.dumps(d.__dict__) + "\n")


def materialise(draws: list[Draw], tasks_root: Path, out_dir: Path, copy: bool = False) -> None:
    """Create `<out_dir>/<index>_<task_id>` entries pointing at built task directories."""
    import shutil

    out_dir.mkdir(parents=True, exist_ok=True)
    width = len(str(len(draws)))
    for d in draws:
        src = tasks_root / d.task_id
        if not src.is_dir():
            raise FileNotFoundError(src)
        dst = out_dir / f"{d.index:0{width}d}_{d.task_id}"
        if dst.exists() or dst.is_symlink():
            continue
        if copy:
            shutil.copytree(src, dst)
        else:
            dst.symlink_to(src.resolve(), target_is_directory=True)
