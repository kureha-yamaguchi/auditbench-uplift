"""Private target-unit manifest: map every annotation to supporting log records (PLAN.md §3.3).

A *target unit* is one annotation record (several timestamps and entity aliases describe one event;
alias products are not independent events). Dataset-specific counting is preserved: OpTC lateral
movement merges records by external host (upstream's unique-host convention). Each target is mapped
to evidence lines in every view (edge and raw) and labelled

  supported_positive   - at least one record in some view matches the timestamp (at annotation
                         precision) and the entity
  ambiguous            - label-quality concern recorded for review (multicast/broadcast/link-local
                         "external host", placeholder "no value"); never counts as a target and a
                         matching finding is neither TP nor FP
  unsupported          - no supporting record found; quarantined with reason

The evidence mapping is deterministic and model-blind. It is a support check, not proof of
solvability, and the manifest is meant to be reviewed before freezing.
"""

from __future__ import annotations

import ipaddress
import json
import re
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from .ground_truth import ENTITY_KIND, Annotation, all_annotations
from .inventory import FileRecord
from .paths import data_input_dir
from .timestamps import PRECISION, line_time, parse_annotation_time, to_precision

# Public canonical list from the upstream persistence prompt (20 MITRE ATT&CK persistence techniques).
PERSISTENCE_TECHNIQUES = [
    "Account Manipulation", "BITS Jobs", "Boot or Logon Autostart Execution",
    "Boot or Logon Initialization Scripts", "Browser Extensions", "Compromise Host Software Binary",
    "Create Account", "Create or Modify System Process", "Event Triggered Execution",
    "External Remote Services", "Hijack Execution Flow", "Implant Internal Image",
    "Modify Authentication Process", "Office Application Startup", "Power Settings", "Pre-OS Boot",
    "Scheduled Task/Job", "Server Software Component", "Traffic Signaling", "Valid Accounts",
]

# Record-level indicators used only to locate supporting evidence for persistence targets.
# They are deliberately broad; a hit means "a record consistent with this technique exists at the
# annotated time", which the manifest reviewer then confirms.
TECHNIQUE_INDICATORS: dict[str, list[str]] = {
    "Account Manipulation": [r"authorized_keys", r"\busermod\b", r"\bchage\b", r"net\s+(user|localgroup)", r"\bgpasswd\b", r"public-key"],
    "Create Account": [r"\buseradd\b", r"\badduser\b", r"net\s+user\s+\S+\s+\S+\s+/add", r"\bnewusers\b", r"/etc/passwd"],
    "Modify Authentication Process": [r"sshd_config", r"/etc/pam\.d", r"\bpasswd\b", r"/etc/shadow", r"lsass", r"Authentication Packages"],
    "External Remote Services": [r"\bplink\b", r"\bsshd?\b", r"ms-wbt-server|\b3389\b", r"\bvnc\b", r"openvpn|wireguard|ngrok|teamviewer|anydesk", r"PUTTY", r"\bss -tuln\b"],
    "Boot or Logon Initialization Scripts": [r"rc\.local", r"\.bashrc|\.bash_profile|\.profile|/etc/profile", r"/etc/init\.d", r"logon", r"Startup"],
    "Boot or Logon Autostart Execution": [r"CurrentVersion\\+Run", r"systemd/system/.*\.service", r"rc-local\.service", r"autostart", r"\\Startup\\", r"\.desktop\b", r"Winlogon"],
    "Scheduled Task/Job": [r"\bcrontab\b|/var/spool/cron|/etc/cron", r"\bschtasks\b", r"task_name|\\Windows\\System32\\Tasks", r"\bat\.exe\b", r"\.timer\b"],
    "Event Triggered Execution": [r"wmiprvse|wmic|__EventFilter|EventConsumer|FilterToConsumerBinding", r"\btrap\b", r"Image File Execution Options", r"\.bashrc", r"cscript|\.vbs\b", r"reg\.exe"],
    "Create or Modify System Process": [r"systemctl\s+(enable|daemon-reload)", r"\bsc\.exe\b|\bsc\s+create\b", r"/etc/systemd/system", r"services\.exe"],
    "Hijack Execution Flow": [r"LD_PRELOAD|/etc/ld\.so", r"\.dll\b.*(Temp|AppData)", r"PATH="],
    "Valid Accounts": [r"\bsu\b|\bsudo\b|logon|LogonType"],
}


@dataclass
class Target:
    target_id: str
    dataset: str
    task: str
    scenario: str
    scenario_key: str
    entity_kind: str
    aliases: list[str]
    timestamps: list[str]            # annotation strings as given
    timestamps_norm: list[str]       # normalised to task precision, deduplicated
    precision: str
    status: str                      # supported_positive | ambiguous | unsupported
    reason: str
    evidence: dict[str, list[int]] = field(default_factory=dict)   # rel_path -> 1-based line numbers
    merged_records: int = 1
    extra: dict = field(default_factory=dict)


def _is_suspicious_host(alias: str) -> str | None:
    try:
        ip = ipaddress.ip_address(alias)
    except ValueError:
        return None
    if ip.is_multicast:
        return "multicast destination annotated as lateral-movement host"
    if ip.is_link_local:
        return "link-local destination annotated as lateral-movement host"
    if isinstance(ip, ipaddress.IPv4Address) and alias.endswith(".255"):
        return "broadcast destination annotated as lateral-movement host"
    return None


def _normalise_aliases(kind: str, aliases: list[str]) -> list[str]:
    out = []
    for a in aliases:
        a = a.strip()
        if not a or a.lower() == "no value":
            continue
        out.append(a)
    return out


def _alias_patterns(kind: str, aliases: list[str]) -> list[re.Pattern]:
    pats = []
    for a in aliases:
        esc = re.escape(a)
        if kind == "path":
            # logs may double backslashes ("\\\\Device") relative to the annotation
            esc = esc.replace(re.escape("\\"), r"\\{1,4}")
        pats.append(re.compile(esc, re.IGNORECASE))
    return pats


def _in_window(dt: datetime, stamps: list[datetime], precision: str) -> bool:
    if precision == "second":
        return any(dt.replace(microsecond=0) == s for s in stamps)
    return any(s <= dt < s + timedelta(minutes=1) for s in stamps)


def map_target_evidence(target: Target, files: list[FileRecord]) -> dict[str, list[int]]:
    stamps = [parse_annotation_time(t)[0] for t in target.timestamps]
    if target.entity_kind == "technique":
        technique = target.aliases[0]
        pats = [re.compile(p, re.IGNORECASE) for p in TECHNIQUE_INDICATORS.get(technique, [])]
    else:
        pats = _alias_patterns(target.entity_kind, target.aliases)
    evidence: dict[str, list[int]] = {}
    for f in files:
        hits = []
        with (data_input_dir() / f.rel_path).open(errors="replace") as fh:
            for i, line in enumerate(fh, start=1):
                dt = line_time(line, f.representation)
                if dt is None or not _in_window(dt, stamps, target.precision):
                    continue
                if any(p.search(line) for p in pats):
                    hits.append(i)
        if hits:
            evidence[f.rel_path] = hits
    return evidence


def build_targets(records: list[FileRecord], annotations: list[Annotation] | None = None) -> list[Target]:
    annotations = annotations if annotations is not None else all_annotations()
    files_by_scenario: dict[tuple[str, str, str], list[FileRecord]] = defaultdict(list)
    for r in records:
        files_by_scenario[(r.dataset, r.task, r.scenario)].append(r)

    # Group annotation records into units.
    units: list[tuple[Annotation, list[Annotation]]] = []
    by_scenario: dict[tuple, list[Annotation]] = defaultdict(list)
    for a in annotations:
        by_scenario[(a.dataset, a.task, a.scenario)].append(a)
    for key, recs in by_scenario.items():
        dataset, task, _ = key
        if dataset == "optc" and task == "lm":
            # unique-host convention: merge records that name the same external host
            by_host: dict[str, list[Annotation]] = defaultdict(list)
            for a in recs:
                by_host[a.entities[0]].append(a)
            for host, members in by_host.items():
                merged = Annotation(dataset, task, members[0].scenario, members[0].record_index,
                                    sorted({t for m in members for t in m.timestamps}), [host],
                                    {"usernames": sorted({u for m in members for u in m.extra.get("username", [])})})
                units.append((merged, members))
        elif task == "persistence":
            # one unit per technique named in the record; timestamps are shared candidates
            for a in recs:
                for tech in a.entities:
                    units.append((Annotation(dataset, task, a.scenario, a.record_index, a.timestamps, [tech], a.extra), [a]))
        else:
            for a in recs:
                units.append((a, [a]))

    targets: list[Target] = []
    for ann, members in units:
        key = (ann.dataset, ann.task, ann.scenario)
        files = files_by_scenario.get(key, [])
        precision = PRECISION[(ann.dataset, ann.task)]
        kind = ENTITY_KIND[ann.task]
        aliases = _normalise_aliases(kind, ann.entities)
        norm = sorted({to_precision(parse_annotation_time(t)[0], precision) for t in ann.timestamps})
        scenario_key = files[0].scenario_key if files else f"{ann.dataset}/{ann.scenario}"
        tid = f"{ann.dataset}:{ann.task}:{ann.scenario}:{len([t for t in targets if t.scenario == ann.scenario and t.dataset == ann.dataset and t.task == ann.task])}"
        target = Target(tid, ann.dataset, ann.task, ann.scenario, scenario_key, kind, aliases, list(ann.timestamps),
                        norm, precision, "unsupported", "", {}, len(members), dict(ann.extra))
        if kind == "technique" and aliases and aliases[0] not in PERSISTENCE_TECHNIQUES:
            target.status, target.reason = "ambiguous", f"technique {aliases[0]!r} not in canonical list"
        elif not aliases:
            target.status, target.reason = "ambiguous", "annotation has no concrete entity (placeholder 'no value')"
        elif kind == "host" and (why := _is_suspicious_host(aliases[0])):
            target.status, target.reason = "ambiguous", why
        elif not files:
            target.status, target.reason = "unsupported", "no scenario file for this annotation in data/input"
        else:
            target.evidence = map_target_evidence(target, files)
            if target.evidence:
                target.status, target.reason = "supported_positive", "entity and timestamp found in log records"
            else:
                target.status, target.reason = "unsupported", "no record matches annotated time and entity"
        if target.status == "ambiguous" and files:
            target.evidence = map_target_evidence(target, files)  # keep evidence for review even if ambiguous
        targets.append(target)
    return targets


def write_targets(targets: list[Target], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as fh:
        for t in targets:
            fh.write(json.dumps(asdict(t)) + "\n")


def load_targets(path: Path) -> list[Target]:
    return [Target(**json.loads(line)) for line in path.read_text().splitlines() if line.strip()]


def summarize_targets(targets: list[Target]) -> dict:
    from collections import Counter

    out: dict = {"by_status": dict(Counter(t.status for t in targets))}
    cells = Counter((t.dataset, t.task, t.status) for t in targets)
    out["by_dataset_task_status"] = {f"{d}/{k}/{s}": n for (d, k, s), n in sorted(cells.items())}
    out["quarantined"] = [{"target_id": t.target_id, "status": t.status, "reason": t.reason, "aliases": t.aliases}
                          for t in targets if t.status != "supported_positive"]
    return out
