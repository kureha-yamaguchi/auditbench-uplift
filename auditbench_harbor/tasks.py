"""Build Harbor task directories from canonical units (PLAN.md §3.6).

<task_id>/
  task.toml                  schema 1.4; no-network baseline; separate verifier
  instruction.md
  environment/Dockerfile     agent image: pinned base, log slice read-only
  environment/audit.log
  solution/solve.sh          oracle (copied only for the oracle agent)
  tests/Dockerfile           verifier image, built from tests/ (never in the agent image)
  tests/test.sh
  tests/ground_truth.json    private target manifest for this unit
  tests/audit.log            private copy of the slice for evidence grounding
  tests/grader/              copy of the stdlib-only grader package
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

from .labels import Target
from .paths import REPO_ROOT, data_input_dir
from .templates import ENV_DOCKERFILE, TEST_SH, TESTS_DOCKERFILE, render_instruction
from .timestamps import PRECISION, extract_raw_time
from .windows import TaskUnit
from grader.ground_truth_schema import GroundTruth

GRADER_SRC = REPO_ROOT / "grader"


def _task_toml(unit: TaskUnit) -> str:
    return f'''schema_version = "1.4"
artifacts = ["/app/findings.json"]

[metadata]
suite = "auditbench-agent-v1"
task = "{unit.task}"
log_format = "{unit.representation}"
os = "{unit.os}"

[environment]
network_mode = "no-network"
cpus = 1
memory_mb = 1024
storage_mb = 1024
build_timeout_sec = 600

[agent]
timeout_sec = 1200.0
user = "agent"

[verifier]
timeout_sec = 300.0
environment_mode = "separate"
user = "root"
'''


def _slice_lines(rel_path: str, start: int, end: int) -> list[bytes]:
    out = []
    with (data_input_dir() / rel_path).open("rb") as fh:
        for i, line in enumerate(fh, start=1):
            if i < start:
                continue
            if i > end:
                break
            out.append(line if line.endswith(b"\n") else line + b"\n")
    return out


def _oracle_findings(unit: TaskUnit, targets: dict[str, Target], lines: list[bytes]) -> list[dict]:
    if unit.task == "classification":
        return [{"verdict": "HIGH_SUSPICIOUS" if unit.label == "attack" else "LOW_SUSPICIOUS", "source_lines": []}]
    entity_key = {"lm": "external_host", "persistence": "technique", "exfiltration": "file_path"}[unit.task]
    findings = []
    for tid in unit.supported_targets:
        t = targets[tid]
        local = [ln - unit.start_line + 1 for ln in t.evidence[unit.rel_path] if unit.start_line <= ln <= unit.end_line]
        first = lines[local[0] - 1].decode("utf-8", errors="replace")
        findings.append({
            "timestamp": extract_raw_time(first, unit.representation),
            entity_key: _alias_on_line(t, first),
            "source_lines": local[:32],
            "verdict": "HIGH_SUSPICIOUS",
        })
    return findings


def _alias_on_line(t: Target, line: str) -> str:
    """Techniques are not log strings; for hosts/paths pick the alias the evidence line contains."""
    if t.entity_kind == "technique":
        return t.aliases[0]
    low = line.lower().replace("\\\\", "\\")
    for a in t.aliases:
        if a.lower().replace("\\\\", "\\") in low:
            return a
    return t.aliases[0]


def _ground_truth(unit: TaskUnit, targets: dict[str, Target]) -> dict:
    relevant = [targets[t] for t in unit.supported_targets + unit.ambiguous_targets]
    gt = GroundTruth(
        task=unit.task,
        label=unit.label,
        dataset=unit.dataset,
        representation=unit.representation,
        os=unit.os,
        entity_kind={"lm": "host", "persistence": "technique", "exfiltration": "path", "classification": "none"}[unit.task],
        precision=PRECISION.get((unit.dataset, unit.task), "second"),
        n_lines=unit.n_lines,
        targets=[{"target_id": t.target_id, "timestamps_norm": t.timestamps_norm, "aliases": t.aliases, "status": t.status}
                 for t in relevant],
    )
    return gt.__dict__


def build_task(unit: TaskUnit, targets: dict[str, Target], out_root: Path) -> Path:
    task_dir = out_root / unit.task_id
    if task_dir.exists():
        shutil.rmtree(task_dir)
    (task_dir / "environment").mkdir(parents=True)
    (task_dir / "solution").mkdir()
    (task_dir / "tests").mkdir()

    lines = _slice_lines(unit.rel_path, unit.start_line, unit.end_line)
    assert len(lines) == unit.n_lines, (unit.task_id, len(lines), unit.n_lines)
    slice_bytes = b"".join(lines)
    (task_dir / "environment" / "audit.log").write_bytes(slice_bytes)
    (task_dir / "tests" / "audit.log").write_bytes(slice_bytes)

    (task_dir / "task.toml").write_text(_task_toml(unit))
    (task_dir / "instruction.md").write_text(render_instruction(unit.task, unit.representation, unit.dataset, unit.os, unit.n_lines))
    (task_dir / "environment" / "Dockerfile").write_text(ENV_DOCKERFILE)
    (task_dir / "tests" / "Dockerfile").write_text(TESTS_DOCKERFILE)
    (task_dir / "tests" / "test.sh").write_text(TEST_SH)
    (task_dir / "tests" / "ground_truth.json").write_text(json.dumps(_ground_truth(unit, targets), indent=1))
    shutil.copytree(GRADER_SRC, task_dir / "tests" / "grader", ignore=shutil.ignore_patterns("__pycache__", "fixtures", "*.pyc"))

    oracle = json.dumps(_oracle_findings(unit, targets, lines), indent=1)
    (task_dir / "solution" / "solve.sh").write_text("#!/bin/bash\nset -eu\ncat > /app/findings.json <<'JSON'\n" + oracle + "\nJSON\n")
    _normalise_modes(task_dir)
    return task_dir


def _normalise_modes(task_dir: Path) -> None:
    # Harbor uploads solution/ and tests/ as permission-preserving tarballs; a restrictive host umask
    # (e.g. 0007) would otherwise leave root-owned 0770 directories the unprivileged agent cannot enter.
    for p in [task_dir, *task_dir.rglob("*")]:
        p.chmod(0o755 if p.is_dir() or p.suffix == ".sh" else 0o644)


def slice_sha256(unit: TaskUnit) -> str:
    return hashlib.sha256(b"".join(_slice_lines(unit.rel_path, unit.start_line, unit.end_line))).hexdigest()
