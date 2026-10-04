"""Provenance graph: files are nodes, shared provenance creates edges, components are split groups.

Every edge carries its rule and evidence so grouping decisions are auditable (PLAN.md §3.1).
Edge strengths:
  strong  - used for grouping by default
  weak    - reported, used only with `include_weak=True` (e.g. OpTC same-campaign-day links)
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path

from .ground_truth import Annotation
from .inventory import FileRecord


@dataclass
class Edge:
    a: str  # rel_path
    b: str
    rule: str
    strength: str  # strong | weak
    evidence: str


def _dt(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%d %H:%M:%S")


def _overlap(r1: FileRecord, r2: FileRecord, slack: timedelta = timedelta(0)) -> bool:
    s1, e1, s2, e2 = _dt(r1.window_start), _dt(r1.window_end), _dt(r2.window_start), _dt(r2.window_end)
    return s1 <= e2 + slack and s2 <= e1 + slack


def _scenario_number(name: str) -> str | None:
    m = re.search(r"scenario(\d+)$", name)
    return m.group(1) if m else None


def build_edges(records: list[FileRecord], annotations: list[Annotation]) -> list[Edge]:
    edges: list[Edge] = []

    def add(a: FileRecord, b: FileRecord, rule: str, strength: str, evidence: str) -> None:
        if a.rel_path == b.rel_path:
            return
        x, y = sorted((a.rel_path, b.rel_path))
        edges.append(Edge(x, y, rule, strength, evidence))

    # 1. same dataset-qualified scenario name (raw/edge views, copies across task folders)
    groups: dict[str, list[FileRecord]] = defaultdict(list)
    for r in records:
        groups[r.scenario_key].append(r)
    for key, members in groups.items():
        for i in range(1, len(members)):
            add(members[0], members[i], "same_scenario_key", "strong", key)

    # 2. exact duplicate contents
    by_hash: dict[str, list[FileRecord]] = defaultdict(list)
    for r in records:
        by_hash[r.sha256].append(r)
    for h, members in by_hash.items():
        for i in range(1, len(members)):
            add(members[0], members[i], "identical_content", "strong", h[:16])

    # 3. window overlap on the same dataset, OS and host (Lab: one host per OS; OpTC: hNNN)
    for i, r1 in enumerate(records):
        for r2 in records[i + 1:]:
            if r1.dataset != r2.dataset or r1.os != r2.os or r1.host != r2.host:
                continue
            if r1.scenario_key == r2.scenario_key:
                continue
            if _overlap(r1, r2):
                add(r1, r2, "window_overlap_same_host", "strong",
                    f"{r1.window_start}..{r1.window_end} overlaps {r2.window_start}..{r2.window_end}")

    # 4. classification view named after an investigation scenario ("attack-windows-lmscenario1" ~ "lm-scenario1")
    for r in records:
        if r.task != "classification":
            continue
        m = re.search(r"attack-(?:linux|windows)-([a-z]+)scenario(\d+)$", r.scenario)
        if not m:
            continue
        target_key = f"{r.dataset}/{m.group(1)}-scenario{m.group(2)}"
        for other in records:
            if other.scenario_key == target_key:
                add(r, other, "classification_view_name", "strong", f"{r.scenario} -> {target_key}")

    # 5. annotation timestamps of one scenario falling inside another file's window on the same host/OS
    #    (e.g. Lab lm-scenario3 15:08:37 lies inside exfiltration-scenario5's Windows window)
    for ann in annotations:
        home = [r for r in records if r.dataset == ann.dataset and r.scenario == ann.scenario and r.task == ann.task]
        for ts in ann.timestamps:
            try:
                t = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                t = datetime.strptime(ts, "%Y-%m-%d %H:%M")
            for r in records:
                if r.dataset != ann.dataset or r.scenario == ann.scenario:
                    continue
                if home and (r.os != home[0].os or r.host != home[0].host):
                    continue
                if _dt(r.window_start) <= t <= _dt(r.window_end):
                    for h in home:
                        add(h, r, "annotation_time_inside_window", "strong",
                            f"{ann.dataset}/{ann.scenario} ts {ts} inside {r.filename}")
                    if not home:
                        edges.append(Edge(r.rel_path, f"annotation:{ann.dataset}/{ann.scenario}",
                                          "annotation_without_file_inside_window", "note",
                                          f"{ts} inside {r.filename}"))

    # 6. OpTC: attack files on the same host and campaign day (weak: campaign-level provenance)
    optc_attack = [r for r in records if r.dataset == "optc" and r.label == "attack"]
    for i, r1 in enumerate(optc_attack):
        for r2 in optc_attack[i + 1:]:
            if r1.host == r2.host and r1.window_start[:10] == r2.window_start[:10] and r1.scenario_key != r2.scenario_key:
                add(r1, r2, "optc_same_host_same_day", "strong", f"{r1.host} {r1.window_start[:10]}")
            elif r1.window_start[:10] == r2.window_start[:10] and r1.scenario_key != r2.scenario_key:
                add(r1, r2, "optc_same_campaign_day", "weak", r1.window_start[:10])

    # de-duplicate identical edges
    seen = set()
    unique = []
    for e in edges:
        k = (e.a, e.b, e.rule)
        if k not in seen:
            seen.add(k)
            unique.append(e)
    return unique


def components(records: list[FileRecord], edges: list[Edge], include_weak: bool = False) -> dict[str, str]:
    """Union-find over files. Returns rel_path -> group_id (named after the smallest scenario key)."""
    parent = {r.rel_path: r.rel_path for r in records}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for e in edges:
        if e.strength == "strong" or (include_weak and e.strength == "weak"):
            if e.a in parent and e.b in parent:
                parent[find(e.a)] = find(e.b)

    by_root: dict[str, list[FileRecord]] = defaultdict(list)
    for r in records:
        by_root[find(r.rel_path)].append(r)
    mapping = {}
    for members in by_root.values():
        gid = "g:" + min(m.scenario_key for m in members)
        for m in members:
            mapping[m.rel_path] = gid
    return mapping


def group_table(records: list[FileRecord], mapping: dict[str, str]) -> list[dict]:
    groups: dict[str, dict] = {}
    for r in records:
        g = groups.setdefault(mapping[r.rel_path], {
            "group_id": mapping[r.rel_path], "dataset": r.dataset, "label": r.label, "os": set(),
            "hosts": set(), "tasks": set(), "scenario_keys": set(), "files": [], "representations": set(),
        })
        g["os"].add(r.os)
        if r.host:
            g["hosts"].add(r.host)
        g["tasks"].add(r.task)
        g["scenario_keys"].add(r.scenario_key)
        g["representations"].add(r.representation)
        g["files"].append(r.rel_path)
        if g["label"] != r.label:
            g["label"] = "mixed"
    out = []
    for g in groups.values():
        out.append({k: (sorted(v) if isinstance(v, set) else v) for k, v in g.items()})
    return sorted(out, key=lambda g: g["group_id"])


def write_edges(edges: list[Edge], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as fh:
        for e in edges:
            fh.write(json.dumps(asdict(e)) + "\n")
