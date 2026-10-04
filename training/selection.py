"""Checkpoint eligibility and selection (PLAN.md §5.3, §7.3)."""

from __future__ import annotations

from dataclasses import dataclass

FALSE_ALERT_SLACK = 0.02
VALIDITY_SLACK = 0.01
MIN_IMPROVEMENT = 0.01
PATIENCE = 4
MANIPULATION_TARGET = 0.10


@dataclass
class Evaluation:
    step: int
    D: float | None
    false_alert_rate: float | None
    validity: float | None
    positive_recall: float | None = None


def eligible(e: Evaluation, base: Evaluation) -> tuple[bool, list[str]]:
    reasons = []
    if e.D is None:
        reasons.append("D undefined (missing denominator)")
    if e.false_alert_rate is None or base.false_alert_rate is None or e.false_alert_rate > base.false_alert_rate + FALSE_ALERT_SLACK:
        reasons.append(f"false-alert rate {e.false_alert_rate} > base {base.false_alert_rate} + {FALSE_ALERT_SLACK}")
    if e.validity is None or base.validity is None or e.validity < base.validity - VALIDITY_SLACK:
        reasons.append(f"validity {e.validity} < base {base.validity} - {VALIDITY_SLACK}")
    return (not reasons), reasons


def select(evals: list[Evaluation]) -> dict:
    """Greatest D among eligible checkpoints; ties go to the earlier step; step 0 is eligible."""
    base = next(e for e in evals if e.step == 0)
    best = None
    log = []
    for e in sorted(evals, key=lambda x: x.step):
        ok, why = eligible(e, base)
        log.append({"step": e.step, "D": e.D, "eligible": ok, "reasons": why})
        if ok and (best is None or e.D > best.D):
            best = e
    manipulation_ok = best is not None and best.step > 0 and best.D - base.D >= MANIPULATION_TARGET and \
        (best.positive_recall or 0) > (base.positive_recall or 0)
    return {"selected_step": best.step if best else 0, "selected_D": best.D if best else base.D, "base_D": base.D,
            "manipulation_check_passed": bool(manipulation_ok), "log": log}


def should_stop_early(evals: list[Evaluation]) -> bool:
    """Four consecutive scheduled evaluations without an eligible improvement >= 0.01 over the previous best."""
    base = next(e for e in evals if e.step == 0)
    best = None
    since_improvement = 0
    for e in sorted(evals, key=lambda x: x.step):
        ok, _ = eligible(e, base)
        if ok and (best is None or e.D >= best + MIN_IMPROVEMENT):
            best = e.D
            since_improvement = 0
        else:
            since_improvement += 1
        if since_improvement >= PATIENCE:
            return True
    return False
