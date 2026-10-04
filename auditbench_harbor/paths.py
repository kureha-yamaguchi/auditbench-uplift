"""Locate the AuditBench checkout and this repository's output directories."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PINNED_AUDITBENCH_COMMIT = "369ad441f2876245d0db19990c77ccbcb74a0a3a"

TASKS = ("classification", "lm", "persistence", "exfiltration")
DATASETS = ("lab", "optc")
REPRESENTATIONS = ("edge", "raw")


def auditbench_dir() -> Path:
    """The AuditBench checkout; `data/` inside it is canonical (never `inference/` copies)."""
    raw = os.environ.get("AUDITBENCH_DIR", str(REPO_ROOT.parent / "auditlogsbench"))
    path = Path(raw).expanduser().resolve()
    if not (path / "data" / "input").is_dir():
        raise FileNotFoundError(f"AuditBench data not found under {path}; set AUDITBENCH_DIR")
    return path


def data_input_dir() -> Path:
    return auditbench_dir() / "data" / "input"


def ground_truth_dir() -> Path:
    return auditbench_dir() / "data" / "ground_truth"


def git_state(repo: Path) -> dict:
    """Commit SHA and dirty state of a checkout, for the version manifest."""
    def run(*args: str) -> str:
        return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout.strip()

    sha = run("rev-parse", "HEAD")
    status = run("status", "--porcelain")
    diff_hash = None
    if status:
        import hashlib
        diff_hash = hashlib.sha256(run("diff", "HEAD").encode()).hexdigest()
    return {"commit": sha, "dirty": bool(status), "diff_sha256": diff_hash, "matches_pinned": sha == PINNED_AUDITBENCH_COMMIT}


MANIFESTS_DIR = REPO_ROOT / "manifests"
SPLITS_DIR = REPO_ROOT / "splits"
TASKS_DIR = REPO_ROOT / "tasks"
REPORTS_DIR = REPO_ROOT / "reports"
