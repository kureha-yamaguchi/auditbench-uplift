"""Thin W&B helpers. W&B holds metrics and artifact references; durable files remain authoritative."""

from __future__ import annotations

import json
import os
from pathlib import Path


def init_run(name: str, job_type: str, config: dict | None = None, tags: list[str] | None = None):
    import wandb

    return wandb.init(
        project=os.environ.get("WANDB_PROJECT", "auditbench-uplift"),
        entity=os.environ.get("WANDB_ENTITY") or None,
        name=name, job_type=job_type, config=config or {}, tags=tags or [],
        mode=os.environ.get("WANDB_MODE", "online"),
    )


def log_manifest_artifact(run, name: str, paths: list[Path], root: Path, kind: str = "manifest", metadata: dict | None = None) -> None:
    """Add files/dirs under their repo-relative paths so names never collide."""
    import wandb

    art = wandb.Artifact(name, type=kind, metadata=metadata or {})
    for p in paths:
        rel = str(p.relative_to(root))
        if p.is_dir():
            art.add_dir(str(p), name=rel)
        elif p.exists():
            art.add_file(str(p), name=rel)
    run.log_artifact(art)


def log_table(run, name: str, rows: list[dict]) -> None:
    import wandb

    if not rows:
        return
    cols = sorted({k for r in rows for k in r})
    run.log({name: wandb.Table(columns=cols, data=[[_cell(r.get(c)) for c in cols] for r in rows])})


def _cell(v):
    return json.dumps(v) if isinstance(v, (dict, list)) else v
