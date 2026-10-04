"""Target matching with evidence grounding. Produces per-finding assignments for the reward and
for diagnostics. Semantics (PLAN.md §5.1):

* only HIGH_SUSPICIOUS findings are positives;
* a finding matches a target when its normalised timestamp is one of the target's annotated times
  (at task precision) and its normalised entity is one of the target's aliases;
* a finding must be grounded: at least one referenced source line carries the finding's timestamp
  (at precision) and, for host/path entities, contains the entity; ungrounded findings cannot match;
* each target is covered at most once; further findings on a covered target are redundant, not FP;
* findings matching an *ambiguous* target are neutral; everything else that is HIGH is FP.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .normalize import norm_entity, norm_timestamp
from .schema import Finding
from .timestamps import line_time, to_precision


@dataclass
class TargetSpec:
    target_id: str
    timestamps_norm: list[str]
    aliases: list[str]
    status: str  # supported_positive | ambiguous


@dataclass
class Assignment:
    finding_index: int
    verdict: str
    outcome: str  # tp | redundant | neutral | fp | ungrounded | low_confidence
    target_id: str | None = None
    detail: str = ""


@dataclass
class MatchResult:
    n_targets: int
    tp: int
    fp: int
    matched_targets: list[str]
    assignments: list[Assignment] = field(default_factory=list)


def _grounded(f: Finding, kind: str, precision: str, log_lines: list[str], representation: str, ts_norm: str, entity_norm: str, ci: bool) -> bool:
    for ln in f.source_lines:
        line = log_lines[ln - 1]
        dt = line_time(line, representation)
        if dt is None or to_precision(dt, precision) != ts_norm:
            continue
        if kind == "technique":
            return True
        hay = norm_entity(kind, line, ci) if kind == "path" else line.lower()
        if entity_norm in hay:
            return True
    return False


def match(findings: list[Finding], targets: list[TargetSpec], *, kind: str, precision: str, log_lines: list[str],
          representation: str, case_insensitive_paths: bool) -> MatchResult:
    supported = [t for t in targets if t.status == "supported_positive"]
    covered: set[str] = set()
    tp = fp = 0
    assignments: list[Assignment] = []
    for f in findings:
        if not f.is_high:
            assignments.append(Assignment(f.index, f.verdict, "low_confidence"))
            continue
        ts_norm = norm_timestamp(f.timestamp, precision)
        ent_norm = norm_entity(kind, f.entity, case_insensitive_paths)
        if ts_norm is None:
            fp += 1
            assignments.append(Assignment(f.index, f.verdict, "fp", detail="unparseable timestamp"))
            continue
        if not _grounded(f, kind, precision, log_lines, representation, ts_norm, ent_norm, case_insensitive_paths):
            fp += 1
            assignments.append(Assignment(f.index, f.verdict, "ungrounded", detail="no referenced line supports timestamp/entity"))
            continue
        hit = None
        for t in targets:
            aliases = {norm_entity(kind, a, case_insensitive_paths) for a in t.aliases}
            if ts_norm in t.timestamps_norm and ent_norm in aliases:
                hit = t
                if t.status == "supported_positive":
                    break
        if hit is None:
            fp += 1
            assignments.append(Assignment(f.index, f.verdict, "fp", detail=f"{ts_norm} {ent_norm}"))
        elif hit.status != "supported_positive":
            assignments.append(Assignment(f.index, f.verdict, "neutral", hit.target_id))
        elif hit.target_id in covered:
            assignments.append(Assignment(f.index, f.verdict, "redundant", hit.target_id))
        else:
            covered.add(hit.target_id)
            tp += 1
            assignments.append(Assignment(f.index, f.verdict, "tp", hit.target_id))
    return MatchResult(len(supported), tp, fp, sorted(covered), assignments)
