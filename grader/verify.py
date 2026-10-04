"""Verifier entrypoint. Runs inside the (separate) verifier container.

Inputs:  the agent's `/app/findings.json`, delivered as a Harbor artifact at
         /logs/artifacts/app/findings.json (separate verifier) or present at /app/findings.json
         (shared verifier); the immutable `/tests/ground_truth.json`; the immutable `/app/audit.log`.
Outputs: /logs/verifier/reward.json  -> {"reward": R} only
         /logs/verifier/diagnostics.json -> everything else (never consumed by the learner)
"""

from __future__ import annotations

import json
import os
import sys
import traceback
from pathlib import Path

from . import GRADER_VERSION
from .matching import TargetSpec, match
from .reward import dense_reward, strict_reward
from .schema import SchemaError, load_findings

ARTIFACT_OUTPUT = Path("/logs/artifacts/app/findings.json")
AGENT_OUTPUT = Path("/app/findings.json")
LOG_PATH = Path("/app/audit.log")
GROUND_TRUTH = Path("/tests/ground_truth.json")
VERIFIER_DIR = Path("/logs/verifier")


def grade(output_path: Path, ground_truth: dict, log_path: Path) -> tuple[float, dict]:
    task, label = ground_truth["task"], ground_truth["label"]
    log_lines = log_path.read_text(errors="replace").splitlines()
    if len(log_lines) != ground_truth["n_lines"]:
        raise RuntimeError(f"audit.log has {len(log_lines)} lines; manifest expects {ground_truth['n_lines']}")
    diag: dict = {"grader_version": GRADER_VERSION, "task": task, "label": label, "schema_valid": False}
    try:
        findings = load_findings(output_path, task, len(log_lines))
    except SchemaError as e:
        diag["schema_error"] = str(e)
        diag["termination"] = "invalid_output"
        return 0.0, diag
    diag["schema_valid"] = True
    diag["n_findings"] = len(findings)
    diag["n_high"] = sum(f.is_high for f in findings)
    result = None
    if task != "classification":
        targets = [TargetSpec(**t) for t in ground_truth["targets"]]
        result = match(findings, targets, kind=ground_truth["entity_kind"], precision=ground_truth["precision"],
                       log_lines=log_lines, representation=ground_truth["representation"],
                       case_insensitive_paths=ground_truth["os"] == "windows")
        diag.update({
            "n_targets": result.n_targets, "tp": result.tp, "fp": result.fp,
            "matched_targets": result.matched_targets,
            "assignments": [a.__dict__ for a in result.assignments],
        })
    reward = strict_reward(task, label, findings, result)
    diag["strict_success"] = reward
    diag["dense_reward"] = dense_reward(task, label, findings, result)
    diag["termination"] = "graded"
    return reward, diag


def main() -> int:
    VERIFIER_DIR.mkdir(parents=True, exist_ok=True)
    output = ARTIFACT_OUTPUT if ARTIFACT_OUTPUT.exists() or ARTIFACT_OUTPUT.is_symlink() else AGENT_OUTPUT
    reward, diag = 0.0, {"termination": "verifier_error"}
    try:
        ground_truth = json.loads(GROUND_TRUTH.read_text())
        reward_mode = os.environ.get("AUDITBENCH_REWARD", "strict")
        reward, diag = grade(output, ground_truth, LOG_PATH)
        if reward_mode == "dense":
            reward = diag["dense_reward"]
        diag["reward_mode"] = reward_mode
        diag["output_path"] = str(output)
    except Exception as e:  # infrastructure/verifier failure: distinct from a wrong answer
        diag["verifier_exception"] = f"{type(e).__name__}: {e}"
        diag["traceback"] = traceback.format_exc()
        (VERIFIER_DIR / "diagnostics.json").write_text(json.dumps(diag, indent=1))
        print(diag["verifier_exception"], file=sys.stderr)
        return 2  # no reward file written: Harbor reports a verifier error, not reward 0
    (VERIFIER_DIR / "diagnostics.json").write_text(json.dumps(diag, indent=1))
    (VERIFIER_DIR / "reward.json").write_text(json.dumps({"reward": float(reward)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
