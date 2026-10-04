#!/usr/bin/env python
"""Index a Harbor job (or SkyRL trials dir) into trajectory records: trajectories/<name>.jsonl."""
import argparse
import json
from pathlib import Path

from auditbench_harbor.paths import REPO_ROOT
from training.trajectories import index_job


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("job_dir")
    ap.add_argument("--name", required=True, help="e.g. baseline-train, dev-step-0010")
    ap.add_argument("--split", default=None)
    ap.add_argument("--policy", default=None, help='JSON, e.g. {"arm":"defence","step":10}')
    args = ap.parse_args()
    out = REPO_ROOT / "trajectories" / f"{args.name}.jsonl"
    n = index_job(Path(args.job_dir), out, split=args.split, policy=json.loads(args.policy) if args.policy else None)
    print(f"{n} trials -> {out}")


if __name__ == "__main__":
    main()
