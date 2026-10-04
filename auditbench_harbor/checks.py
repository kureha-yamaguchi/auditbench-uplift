"""Gate-B checks that run without a sandbox provider: schema acceptance, leakage, oracle grading."""

from __future__ import annotations

import json
import re
import subprocess
import tempfile
from pathlib import Path

from grader.matching import TargetSpec, match
from grader.reward import strict_reward
from grader.schema import SchemaError, load_findings

from .labels import Target
from .windows import TaskUnit

# Strings that must never appear in anything the agent can read. Entities that legitimately occur
# in the logs (hosts, paths, technique words) are *not* banned (PLAN.md §3.6).
_FORBIDDEN_PATTERNS = [
    re.compile(r"scenario\d+"), re.compile(r"groundtruth"), re.compile(r"ground_truth"),
    re.compile(r"\bbenign-"), re.compile(r"\battack-(linux|windows)"), re.compile(r"\bh\d{3}_"),
    re.compile(r"supported_positive"), re.compile(r"target_id"),
]


def validate_task_toml(task_dir: Path) -> list[str]:
    """Parse task.toml with the pinned Harbor schema; return problems."""
    from harbor.models.task.config import NetworkMode, TaskConfig, VerifierEnvironmentMode

    cfg = TaskConfig.model_validate_toml((task_dir / "task.toml").read_text())
    problems = []
    if cfg.environment.network_mode != NetworkMode.NO_NETWORK:
        problems.append("environment network_mode is not no-network")
    if cfg.verifier.environment_mode != VerifierEnvironmentMode.SEPARATE:
        problems.append("verifier is not separate")
    if "/app/findings.json" not in [a if isinstance(a, str) else a.source for a in cfg.artifacts]:
        problems.append("findings artifact not declared")
    if cfg.schema_version != "1.4":
        problems.append(f"schema_version {cfg.schema_version}")
    return problems


def leakage_check(task_dir: Path, expected_slice_sha256: str) -> list[str]:
    """Agent-visible files: instruction, environment/. Verifier-only material must not be there."""
    import hashlib

    problems = []
    visible = [task_dir / "instruction.md", task_dir / "task.toml", *sorted((task_dir / "environment").rglob("*"))]
    for p in visible:
        if p.name == "audit.log":
            if hashlib.sha256(p.read_bytes()).hexdigest() != expected_slice_sha256:
                problems.append("environment/audit.log differs from the designated source slice")
            continue
        if p.is_dir():
            continue
        text = p.read_text(errors="replace")
        for pat in _FORBIDDEN_PATTERNS:
            if pat.search(text):
                problems.append(f"{p.relative_to(task_dir)} matches forbidden pattern {pat.pattern!r}")
    if set(p.name for p in (task_dir / "environment").iterdir()) != {"Dockerfile", "audit.log"}:
        problems.append("environment/ contains unexpected files")
    return problems


def grade_oracle(task_dir: Path) -> tuple[float, dict]:
    """Run solve.sh in a scratch dir and grade its output in-process with the task's own grader copy."""
    gt = json.loads((task_dir / "tests" / "ground_truth.json").read_text())
    with tempfile.TemporaryDirectory() as tmp:
        script = (task_dir / "solution" / "solve.sh").read_text().replace("/app/findings.json", f"{tmp}/findings.json")
        subprocess.run(["bash", "-c", script], check=True)
        out = Path(tmp) / "findings.json"
        return grade_output(out, gt, task_dir / "tests" / "audit.log")


def grade_output(output: Path, gt: dict, log_path: Path) -> tuple[float, dict]:
    log_lines = log_path.read_text(errors="replace").splitlines()
    try:
        findings = load_findings(output, gt["task"], len(log_lines))
    except SchemaError as e:
        return 0.0, {"schema_error": str(e)}
    result = None
    if gt["task"] != "classification":
        result = match(findings, [TargetSpec(**t) for t in gt["targets"]], kind=gt["entity_kind"], precision=gt["precision"],
                       log_lines=log_lines, representation=gt["representation"], case_insensitive_paths=gt["os"] == "windows")
    r = strict_reward(gt["task"], gt["label"], findings, result)
    return r, {"tp": result.tp if result else None, "fp": result.fp if result else None,
               "n_targets": result.n_targets if result else None,
               "assignments": [a.__dict__ for a in result.assignments] if result else None}


def run_all_checks(units: list[TaskUnit], targets: dict[str, Target], tasks_root: Path, slice_hashes: dict[str, str]) -> dict:
    report = {"n_tasks": 0, "toml_problems": {}, "leakage_problems": {}, "oracle_failures": {}, "oracle_pass": 0}
    for u in units:
        d = tasks_root / u.task_id
        if not d.exists():
            continue
        report["n_tasks"] += 1
        if p := validate_task_toml(d):
            report["toml_problems"][u.task_id] = p
        if p := leakage_check(d, slice_hashes[u.task_id]):
            report["leakage_problems"][u.task_id] = p
        reward, diag = grade_oracle(d)
        if reward == 1.0:
            report["oracle_pass"] += 1
        else:
            report["oracle_failures"][u.task_id] = diag
    return report
