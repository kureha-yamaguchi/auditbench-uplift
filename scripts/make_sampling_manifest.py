#!/usr/bin/env python
"""Draw a balanced training sequence and materialise it as a Harbor task directory.

    python scripts/make_sampling_manifest.py --config configs/training/pilot.yaml

Writes manifests/sampling/<run>.jsonl (every draw with its probability) and an exposure report, and
creates <train_dir> with one symlink per draw so the unmodified harbor-train dataset loader sees
exactly iterations x prompts entries (epochs must be 1).
"""
import argparse
import json
from pathlib import Path

import yaml

from auditbench_harbor.cli import UNITS_DIR
from auditbench_harbor.paths import REPO_ROOT, TASKS_DIR
from auditbench_harbor.windows import load_units
from training.sampler import draw_manifest, exposure_report, materialise, missing_strata, unit_probabilities, write_manifest


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--tasks-root", default=str(TASKS_DIR / "train"))
    ap.add_argument("--materialise", action="store_true", help="also create the symlink dataset at data.train_dir")
    ap.add_argument("--copy", action="store_true", help="copy task dirs instead of symlinking")
    args = ap.parse_args()
    cfg = yaml.safe_load(Path(args.config).read_text())
    units = [u for u in load_units(UNITS_DIR / "train.jsonl") if u.split == "train"]
    if missing := missing_strata(units):
        raise SystemExit(f"missing sampler strata, resolve before freezing: {missing}")
    n = cfg["iterations"] * cfg["prompts_per_iteration"]
    seed = 10_000 + cfg["seed"]  # sampling seed is separate from the training seed
    draws = draw_manifest(units, n, seed)
    out = REPO_ROOT / cfg["data"]["train_manifest"]
    meta = {"run_name": cfg["run_name"], "seed": seed, "n_draws": n, "iterations": cfg["iterations"],
            "prompts_per_iteration": cfg["prompts_per_iteration"], "unit_probabilities": unit_probabilities(units)}
    write_manifest(draws, out, meta)
    report = exposure_report(draws, units)
    out.with_suffix(".exposure.json").write_text(json.dumps(report, indent=1) + "\n")
    train_dir = Path(cfg["data"]["train_dir"]).expanduser()
    if args.materialise:
        materialise(draws, Path(args.tasks_root), train_dir, copy=args.copy)
    print(json.dumps({k: report[k] for k in ("n_draws", "task_frequency", "task_class_frequency", "distinct_units", "distinct_groups", "groups_never_drawn")}, indent=1))
    print(f"manifest: {out}\ndataset:  {train_dir} ({'materialised' if args.materialise else 'not materialised; pass --materialise on the training host'})")


if __name__ == "__main__":
    main()
