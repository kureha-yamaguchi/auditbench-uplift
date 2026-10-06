#!/usr/bin/env python
"""Record the resolved software/hardware environment on the training host (PLAN.md §2)."""
import argparse
import json
import platform
import subprocess
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path


def pkg(name):
    try:
        return version(name)
    except PackageNotFoundError:
        return None


def sh(cmd):
    try:
        return subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=60).stdout.strip()
    except Exception as e:  # noqa: BLE001
        return f"error: {e}"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    info = {
        "python": platform.python_version(), "platform": platform.platform(),
        "packages": {n: pkg(n) for n in ("harbor", "skyrl-train", "vllm", "torch", "transformers", "flash-attn", "ray", "modal", "wandb")},
        "docker": sh("docker --version"),
        "nvidia_smi": sh("nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader"),
        "cuda": sh("nvcc --version | tail -1"),
        "harbor_train_commit": sh("git -C /workspace/auditbench/harbor-train rev-parse HEAD"),
        "harbor_train_local_diff_sha256": sh("git -C /workspace/auditbench/harbor-train diff | sha256sum | cut -d' ' -f1"),
        "harbor_train_patch_sha256": sh("sha256sum patches/harbor-train-9310ef6.patch | cut -d' ' -f1"),
        "repo_commit": sh("git rev-parse HEAD"),
        "repo_dirty": bool(sh("git status --porcelain")),
    }
    out = Path(args.out).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(info, indent=1) + "\n")
    print(json.dumps(info, indent=1))


if __name__ == "__main__":
    main()
