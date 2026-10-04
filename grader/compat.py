"""Pinned upstream-compatibility scorer.

Re-implements the counting conventions of the inspected AuditBench code (commit 369ad441,
`inference/error_analysis/errorinvestigation_v2.py` and `metrics_comp/task_computemetrics.py`) on
structured findings, so adapted runs can also be reported in the paper's units. Documented,
intentional differences from the strict grader:

* matching uses the upstream Cartesian product of annotation timestamps x aliases, with substring
  matching for persistence/exfiltration (`gt in candidate`) and exact timestamp+host for LM;
* only HIGH_SUSPICIOUS counts unless `more_defensive`; no evidence grounding; duplicates count;
* per scenario and attempt: TP is binary for Lab LM, persistence, exfiltration (any hit), and the
  number of unique external hosts for OpTC LM; FN is 1 - TP (binary tasks) or missing unique hosts;
* FP is the number of unmatched high findings summed over chunks; upstream "FPR" is FP / log_lines;
* classification: attack scenario correct iff any chunk is HIGH; benign FP = HIGH chunks / chunks.
  Whole-file classification therefore has exactly one chunk, which is not paper parity.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import product

from .normalize import norm_timestamp
from .schema import HIGH, Finding


@dataclass
class CompatScenario:
    dataset: str
    task: str
    scenario: str
    label: str  # attack | benign
    log_lines: int
    precision: str
    annotations: list[dict]  # raw annotation records: {"timestamp": [...], "<entity field>": [...]}
    entity_field: str


@dataclass
class CompatCounts:
    tp: float = 0
    fp: float = 0
    fn: float = 0
    tn: float = 0
    accuracy: float | None = None
    chunks: int = 0
    detail: dict = field(default_factory=dict)


def _gt_set(sc: CompatScenario) -> set[tuple[str, str]]:
    out = set()
    for rec in sc.annotations:
        out.update(product(rec["timestamp"], [e.replace("\\\\", "\\") for e in rec[sc.entity_field]]))
    return out


def _is_hit(sc: CompatScenario, ts_norm: str, entity: str, gt: set[tuple[str, str]]) -> bool:
    if sc.task == "lm":
        return (ts_norm, entity) in gt
    cand = entity.strip().lower()
    return any(g_ts == ts_norm and g_ent.strip().lower() in cand for g_ts, g_ent in gt)


def score_attempt(sc: CompatScenario, chunk_findings: dict[str, list[Finding] | None], more_defensive: bool = False) -> CompatCounts:
    """`chunk_findings` maps chunk id -> validated findings (None = unparseable chunk, treated as empty,
    matching upstream's parser which silently yields nothing for malformed blocks)."""
    levels = {HIGH, "MEDIUM_SUSPICIOUS"} if more_defensive else {HIGH}
    c = CompatCounts(chunks=len(chunk_findings))
    if sc.task == "classification":
        high_chunks = sum(1 for fs in chunk_findings.values() if fs and any(f.verdict in levels for f in fs))
        if sc.label == "attack":
            c.tp, c.fn = (1, 0) if high_chunks >= 1 else (0, 1)
            c.accuracy = float(c.tp)
        else:
            c.fp, c.tn = high_chunks, c.chunks - high_chunks
            c.accuracy = c.tn / c.chunks if c.chunks else None
        return c
    gt = _gt_set(sc)
    tp_hits: list[tuple[str, str]] = []
    fp = 0
    for fs in chunk_findings.values():
        for f in fs or []:
            if f.verdict not in levels:
                continue
            ts_norm = norm_timestamp(f.timestamp, sc.precision)
            if ts_norm is None:
                continue  # upstream drops findings whose timestamp cannot be converted
            if sc.label == "benign":
                fp += 1
            elif _is_hit(sc, ts_norm, f.entity, gt):
                tp_hits.append((ts_norm, f.entity))
            else:
                fp += 1
    c.fp = fp
    c.tn = sc.log_lines - fp
    if sc.label == "attack":
        if sc.dataset == "optc" and sc.task == "lm":
            unique_hosts = {h for _, h in tp_hits}
            c.tp = len(unique_hosts)
            c.fn = len({e for _, e in gt} - unique_hosts)
        else:
            c.tp = 1 if tp_hits else 0
            c.fn = 1 - c.tp
    c.detail = {"tp_hits": len(tp_hits)}
    return c


def aggregate(counts: list[CompatCounts]) -> dict:
    tp = sum(c.tp for c in counts)
    fp = sum(c.fp for c in counts)
    fn = sum(c.fn for c in counts)
    tn = sum(c.tn for c in counts)
    return {
        "tp": tp, "fp": fp, "fn": fn, "tn": tn,
        "tpr": tp / (tp + fn) if tp + fn else None,
        "fpr": fp / (fp + tn) if fp + tn else None,
    }
