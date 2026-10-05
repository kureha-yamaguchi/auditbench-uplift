#!/usr/bin/env python
"""Enforce the preregistered dollar caps (PLAN.md §7.3, user cap 2026-10-04: $1,500 total).

Tracks node uptime x hourly price in a ledger file on the durable volume and, when a phase or the
total cap is reached, writes STOP and runs the stop command. Also derives the iteration budget for
the main arms from the pilot's measured cost per iteration:

    T_max = min(100, floor(arm_budget / cost_per_iteration))

Usage on the GPU node (background):
    python scripts/spend_guard.py watch --ledger /workspace/auditbench/spend.json --phase pilot --rate 18.36 \
        --stop-file /workspace/auditbench/STOP --stop-cmd "pkill -f main_harbor" --stop-pod self
    python scripts/spend_guard.py iteration-budget --ledger /workspace/auditbench/spend.json --pilot-iterations 10
"""
import argparse
import json
import os
import subprocess
import time
from pathlib import Path

TOTAL_CAP_USD = 1500.0
PHASE_CAPS_USD = {"setup_smoke_baseline": 300.0, "pilot": 250.0, "defence": 475.0, "control": 475.0}


def load(p: Path) -> dict:
    return json.loads(p.read_text()) if p.exists() else {"phases": {}, "events": []}


def save(p: Path, d: dict) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(d, indent=1) + "\n")


def total(d: dict) -> float:
    return sum(ph.get("usd", 0.0) for ph in d["phases"].values())


def watch(args) -> None:
    ledger = Path(args.ledger)
    start = time.time()
    d = load(ledger)
    ph = d["phases"].setdefault(args.phase, {"usd": 0.0, "seconds": 0.0, "rate_per_hour": args.rate})
    base_usd, base_sec = ph["usd"], ph["seconds"]
    while True:
        elapsed = time.time() - start
        ph["seconds"] = base_sec + elapsed
        ph["usd"] = base_usd + elapsed / 3600 * args.rate
        save(ledger, d)
        over = []
        if ph["usd"] >= PHASE_CAPS_USD.get(args.phase, TOTAL_CAP_USD):
            over.append(f"phase {args.phase} cap {PHASE_CAPS_USD.get(args.phase)}")
        if total(d) >= TOTAL_CAP_USD:
            over.append(f"total cap {TOTAL_CAP_USD}")
        if over:
            d["events"].append({"t": time.time(), "stop": over})
            save(ledger, d)
            Path(args.stop_file).write_text("; ".join(over) + "\n")
            if args.stop_cmd:
                subprocess.run(args.stop_cmd, shell=True, check=False)
            if args.stop_pod:
                _stop_pod(os.environ.get("RUNPOD_POD_ID", "") if args.stop_pod == "self" else args.stop_pod)
            print("STOP:", over)
            return
        time.sleep(args.poll_sec)


def _stop_pod(pod_id: str) -> None:
    """Stop the RunPod pod itself (RUNPOD_API_KEY in the environment); last line of defence against idle billing."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("runpod_api", Path(__file__).with_name("runpod_api.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    if not pod_id:
        print("stop pod: no pod id available")
        return
    print("stop pod:", mod.stop(pod_id))


def iteration_budget(args) -> None:
    d = load(Path(args.ledger))
    pilot = d["phases"].get("pilot")
    if not pilot or pilot["usd"] <= 0:
        raise SystemExit("no pilot spend recorded")
    cost_per_iter = pilot["usd"] / args.pilot_iterations
    remaining = TOTAL_CAP_USD - total(d)
    per_arm = min(PHASE_CAPS_USD["defence"], remaining / 2)
    t_max = max(0, min(100, int(per_arm // cost_per_iter)))
    out = {"pilot_usd": pilot["usd"], "cost_per_iteration_usd": round(cost_per_iter, 2), "remaining_usd": round(remaining, 2),
           "per_arm_budget_usd": round(per_arm, 2), "T_max": t_max,
           "rule": "T_max = min(100, floor(per_arm_budget / cost_per_iteration)); control trains to the defence terminal step"}
    print(json.dumps(out, indent=1))


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    w = sub.add_parser("watch")
    w.add_argument("--ledger", required=True)
    w.add_argument("--phase", required=True, choices=list(PHASE_CAPS_USD))
    w.add_argument("--rate", type=float, required=True, help="node $/hour as billed")
    w.add_argument("--stop-file", required=True)
    w.add_argument("--stop-cmd", default=None)
    w.add_argument("--stop-pod", default=None, help="RunPod pod id, or 'self' to read RUNPOD_POD_ID, to stop when a cap trips (needs RUNPOD_API_KEY)")
    w.add_argument("--poll-sec", type=int, default=60)
    w.set_defaults(fn=watch)
    b = sub.add_parser("iteration-budget")
    b.add_argument("--ledger", required=True)
    b.add_argument("--pilot-iterations", type=int, default=10)
    b.set_defaults(fn=iteration_budget)
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
