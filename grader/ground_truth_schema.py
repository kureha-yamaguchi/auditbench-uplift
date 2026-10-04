"""The private per-task manifest written by the builder and read by the verifier."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class GroundTruth:
    task: str                 # lm | persistence | exfiltration | classification
    label: str                # positive | negative_attack_file | benign | attack
    dataset: str
    representation: str
    os: str
    entity_kind: str          # host | technique | path | none
    precision: str            # second | minute
    n_lines: int
    targets: list[dict] = field(default_factory=list)  # {target_id, timestamps_norm, aliases, status}
