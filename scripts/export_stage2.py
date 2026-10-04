#!/usr/bin/env python
"""Write the Stage-2 hand-off index: checkpoints (with checksums), manifests, splits, reports."""
import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from auditbench_harbor.paths import REPO_ROOT


def sha256_dir(path: Path) -> dict[str, str]:
    return {str(p.relative_to(path)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(path.rglob("*")) if p.is_file()}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--checkpoint", action="append", default=[], metavar="NAME=PATH", help="e.g. defence-selected-S=/workspace/auditbench/runs/defence-seed1/exports/global_step_10")
    args = ap.parse_args()
    index = {"created": datetime.now(timezone.utc).isoformat(), "checkpoints": {}, "manifests": {}}
    for item in args.checkpoint:
        name, path = item.split("=", 1)
        p = Path(path)
        index["checkpoints"][name] = {"path": str(p), "files": sha256_dir(p) if p.exists() else None, "present": p.exists()}
    for rel in ("manifests/versions.json", "manifests/inventory.json", "manifests/groups.json", "splits/allocation.json",
                "splits/group_edges.jsonl", "configs/inference_contract.yaml", "reports/gate_b_checks.json"):
        p = REPO_ROOT / rel
        index["manifests"][rel] = hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None
    out = REPO_ROOT / "checkpoints" / "index.json"
    out.write_text(json.dumps(index, indent=1) + "\n")
    print(out)


if __name__ == "__main__":
    main()
