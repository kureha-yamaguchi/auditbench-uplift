#!/usr/bin/env python
"""§8.2 budget sensitivity from measured or assumed inputs. Prints low/central/high forecasts."""
import argparse
import json

H200_PER_GPU_HOUR = 4.59          # RunPod Secure Cloud list price captured 2026-10-03
MODAL_CORE_SEC = 0.00003942       # $/physical-core-second
MODAL_GIB_SEC = 0.00000667        # $/GiB-second


def forecast(n_train, n_dev, n_control, iters, evals, minutes_per_attempt, minutes_per_iteration, gpus=4, cores=1, gib=1):
    r_baseline = 5 * (n_train + n_dev + n_control)
    r_train = 256 * iters
    r_eval = 5 * n_dev * evals
    rollouts = r_baseline + r_train + r_eval
    sandbox_cost = rollouts * minutes_per_attempt * 60 * (cores * MODAL_CORE_SEC + gib * MODAL_GIB_SEC)
    gpu_hours = iters * minutes_per_iteration / 60 + (r_baseline + r_eval) * minutes_per_attempt / 60 / 16  # 16 concurrent eval rollouts
    gpu_cost = gpus * H200_PER_GPU_HOUR * gpu_hours
    return {"rollouts": rollouts, "sandbox_usd": round(sandbox_cost, 2), "gpu_node_hours": round(gpu_hours, 1), "gpu_usd": round(gpu_cost, 2), "total_usd_before_contingency": round(sandbox_cost + gpu_cost, 2)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n-train", type=int, default=367)
    ap.add_argument("--n-dev", type=int, default=78)
    ap.add_argument("--n-control", type=int, default=60)
    ap.add_argument("--iterations", type=int, default=210, help="pilot + defence + control")
    ap.add_argument("--evaluations", type=int, default=21, help="dev evaluations per defence run incl. step 0")
    args = ap.parse_args()
    out = {}
    for name, m_attempt, m_iter in (("low", 5, 15), ("central", 10, 25), ("high", 20, 35)):
        out[name] = forecast(args.n_train, args.n_dev, args.n_control, args.iterations, args.evaluations, m_attempt, m_iter)
    out["note"] = "sensitivity calculation, not measured throughput; replace minutes_per_* with pilot p50/p95 and add storage, egress, builds, retries, contingency"
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
