#!/usr/bin/env python
"""Early-stopping watchdog for a training arm (PLAN.md §7.3).

The trainer owns saves and the hard iteration cap (the sampling manifest fixes the iteration count).
This process watches the per-step dev evaluations produced by score_job.py and, once four consecutive
scheduled evaluations show no eligible improvement >= 0.01 in D, writes a STOP file and optionally
runs a stop command (e.g. `sky exec -c auditbench -- pkill -f main_harbor`). It never deletes anything.
"""
import argparse
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from select_checkpoint import load_evals  # noqa: E402
from training.selection import should_stop_early


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm", required=True)
    ap.add_argument("--stop-file", required=True)
    ap.add_argument("--stop-cmd", default=None)
    ap.add_argument("--poll-sec", type=int, default=300)
    args = ap.parse_args()
    while True:
        evals = load_evals(args.arm)
        if any(e.step == 0 for e in evals) and should_stop_early(evals):
            Path(args.stop_file).write_text(f"early stop after steps {[e.step for e in evals]}\n")
            if args.stop_cmd:
                subprocess.run(args.stop_cmd, shell=True, check=False)
            print("early stop triggered")
            return
        time.sleep(args.poll_sec)


if __name__ == "__main__":
    main()
