"""Index Harbor trial directories into versioned trajectory records (PLAN.md §6.3).

Fields that Harbor 0.23 / Terminus-2 do not emit by default (token ids, logprobs, loss masks) are
recorded as explicit gaps rather than fabricated. Enable `collect_rollout_details` on Terminus-2
to populate `rollout_details`; the record then carries them under `tokens`.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

RECORD_VERSION = "trajectory-record-v1"


def _read_json(p: Path):
    return json.loads(p.read_text()) if p.exists() else None


def index_trial(trial_dir: Path, split: str | None = None, policy: dict | None = None, sampler_prob: float | None = None) -> dict:
    result = _read_json(trial_dir / "result.json") or {}
    diag = _read_json(trial_dir / "verifier" / "diagnostics.json")
    reward = _read_json(trial_dir / "verifier" / "reward.json")
    agent_meta = (result.get("agent_result") or {}).get("metadata") or {}
    rollout = (result.get("agent_result") or {}).get("rollout_details")
    findings_path = trial_dir / "artifacts" / "app" / "findings.json"
    out_bytes = findings_path.read_bytes() if findings_path.exists() else None
    exc = result.get("exception_info") or {}
    termination = "graded" if reward else ("policy_timeout" if exc.get("exception_type") == "AgentTimeoutError"
                                          else "context_exhausted" if exc.get("exception_type") == "ContextLengthExceededError"
                                          else "infrastructure_error" if exc else "unknown")
    gaps = []
    if rollout is None:
        gaps.append("no token ids/logprobs: enable terminus-2 collect_rollout_details")
    if "all_messages" not in agent_meta:
        gaps.append("no all_messages: enable terminus-2 store_all_messages")
    return {
        "record_version": RECORD_VERSION,
        "trial_name": result.get("trial_name") or trial_dir.name,
        "trial_id": result.get("id"),
        "task_name": result.get("task_name"),
        "task_checksum": result.get("task_checksum"),
        "split": split,
        "sampler_probability": sampler_prob,
        "policy": policy,
        "config": result.get("config"),
        "agent_info": result.get("agent_info"),
        "timing": {k: result.get(k) for k in ("started_at", "finished_at", "environment_setup", "agent_setup", "agent_execution", "verifier")},
        "tokens": {"n_input": (result.get("agent_result") or {}).get("n_input_tokens"),
                   "n_output": (result.get("agent_result") or {}).get("n_output_tokens"),
                   "n_episodes": agent_meta.get("n_episodes"), "summarization_count": agent_meta.get("summarization_count"),
                   "rollout_details_present": rollout is not None},
        "messages": agent_meta.get("all_messages"),
        "output": {"bytes": len(out_bytes) if out_bytes is not None else None,
                   "sha256": hashlib.sha256(out_bytes).hexdigest() if out_bytes is not None else None},
        "reward": reward, "diagnostics": diag, "verifier_result": result.get("verifier_result"),
        "exception": exc or None, "termination": termination, "gaps": gaps,
        "artifact_dir": str(trial_dir),
    }


def index_job(job_dir: Path, out_path: Path, **kw) -> int:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with out_path.open("w") as fh:
        for trial_dir in sorted(p for p in job_dir.iterdir() if p.is_dir() and (p / "result.json").exists()):
            fh.write(json.dumps(index_trial(trial_dir, **kw)) + "\n")
            n += 1
    return n
