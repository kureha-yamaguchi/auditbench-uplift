"""Learner-facing reward. Only `{"reward": <finite number>}` reaches the trainer; everything else is
diagnostics (PLAN.md §4, §5.1)."""

from __future__ import annotations

from .matching import MatchResult
from .schema import HIGH, Finding


def strict_reward(task: str, label: str, findings: list[Finding] | None, result: MatchResult | None) -> float:
    """Binary success. `findings is None` means schema-invalid output."""
    if findings is None:
        return 0.0
    if task == "classification":
        is_high = findings[0].verdict == HIGH
        return 1.0 if is_high == (label == "attack") else 0.0
    assert result is not None
    if label == "positive":
        return 1.0 if result.tp == result.n_targets and result.fp == 0 else 0.0
    # negative windows (attack file without annotated targets, or benign file)
    return 1.0 if result.fp == 0 and not any(f.is_high for f in findings) else 0.0


def dense_reward(task: str, label: str, findings: list[Finding] | None, result: MatchResult | None) -> float:
    """Pilot-only contingency: (TP/|G|)/(1+FP) for positive investigation windows; binary otherwise."""
    if findings is None:
        return 0.0
    if task != "classification" and label == "positive":
        assert result is not None
        if result.n_targets == 0:
            return 0.0
        return (result.tp / result.n_targets) / (1 + result.fp)
    return strict_reward(task, label, findings, result)
