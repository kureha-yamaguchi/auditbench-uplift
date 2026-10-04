"""Load the upstream annotation files, preserving their structure (one record = one annotation unit)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from .paths import ground_truth_dir

ENTITY_FIELD = {"lm": "external host", "persistence": "mechanism_name", "exfiltration": "exfiltrated data"}
ENTITY_KIND = {"lm": "host", "persistence": "technique", "exfiltration": "path"}


@dataclass
class Annotation:
    dataset: str
    task: str
    scenario: str  # as written in the annotation file, e.g. "lm-scenario5" (not host-qualified)
    record_index: int
    timestamps: list[str]
    entities: list[str]  # aliases of one target (external hosts, technique names, data paths)
    extra: dict = field(default_factory=dict)


def load_annotations(dataset: str, task: str) -> list[Annotation]:
    path = ground_truth_dir() / dataset / f"groundtruth-{task}.jsonl"
    out: list[Annotation] = []
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        obj = json.loads(line)
        (scenario, records), = obj.items()
        for i, rec in enumerate(records):
            entities = [_unescape(e) for e in rec[ENTITY_FIELD[task]]]
            extra = {k: v for k, v in rec.items() if k not in ("timestamp", ENTITY_FIELD[task])}
            out.append(Annotation(dataset, task, scenario, i, list(rec["timestamp"]), entities, extra))
    return out


def _unescape(value: str) -> str:
    # Upstream JSON stores doubled backslashes for Windows paths/usernames.
    return value.replace("\\\\", "\\")


def annotation_file_hashes() -> dict[str, str]:
    import hashlib

    out = {}
    for p in sorted(ground_truth_dir().glob("*/*.jsonl")):
        out[str(p.relative_to(ground_truth_dir()))] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def all_annotations() -> list[Annotation]:
    out = []
    for dataset in ("lab", "optc"):
        for task in ("lm", "persistence", "exfiltration"):
            if (ground_truth_dir() / dataset / f"groundtruth-{task}.jsonl").exists():
                out.extend(load_annotations(dataset, task))
    return out
