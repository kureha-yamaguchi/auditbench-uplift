#!/usr/bin/env python
"""First-pass screening of the control pool `open-thoughts/OpenThoughts-TB-dev` (PLAN.md §7.4).

Downloads only instruction.md and task.toml for every task at the pinned revision, applies the
keyword rubric, and writes manifests/control_review.jsonl with a `screen` status per task
(exclude | review | candidate). Keyword screening is a first pass: every row carries the matched
terms and an empty `reviewer_decision` field to be filled by hand before the pool is frozen.
"""
from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

from huggingface_hub import HfApi, hf_hub_download

from auditbench_harbor.paths import REPO_ROOT

DATASET = "open-thoughts/OpenThoughts-TB-dev"
REVISION = "0d54f719f34dca712c8d6ef0f51df4670a2a287a"

EXCLUDE_TERMS = [
    r"\bmalware\b", r"\bexploit", r"\bvulnerab", r"\bctf\b", r"capture.the.flag", r"\bpentest", r"penetration test",
    r"\breverse.?engineer", r"\bforensic", r"\bintrusion", r"\battack", r"\bphish", r"\bransom", r"\bbackdoor",
    r"\brootkit", r"\bshellcode", r"\bpayload", r"\bc2\b|command.and.control", r"\bbrute.?force", r"\bcredential",
    r"\bprivilege escalation", r"\bexfiltrat", r"\blateral movement", r"\bpersistence mechanism", r"\bsiem\b",
    r"\baudit log", r"\bauditd\b", r"\bsecurity (log|event|incident|alert)", r"\bthreat", r"\bsuspicious",
    r"\bfirewall rule", r"\bids\b|\bips\b", r"\bcve-\d", r"\bsql injection", r"\bxss\b", r"\bpassword crack",
    r"\bhash crack", r"\bjohn the ripper|hashcat|metasploit|nmap|wireshark|pcap",
]
REVIEW_TERMS = [r"\blog file", r"\baccess\.log", r"\bsyslog", r"\bauth", r"\bencrypt", r"\bdecrypt", r"\bcipher", r"\bnetwork",
                r"\bsocket", r"\bssh\b", r"\bfirewall", r"\bpermission", r"\bsecurity", r"\bbinary analysis", r"\bdisassembl"]
RUBRIC = """Control-pool rubric (frozen before main runs):
EXCLUDE: offensive or defensive security content (attack/defence, malware, vulnerabilities, exploitation,
         CTF, forensics, SIEM/audit-log analysis, credential attacks), anything sharing assets or
         solutions with CyberGym, ExploitBench, AuditBench or ExCyTIn-Bench.
PREFER:  routine text/file transformation, data manipulation, shell tasks with comparable
         read/search/write behaviour, resource needs within 1 CPU / 1 GiB or an explicitly recorded exception.
REVIEW:  generic logs, crypto utilities, networking, auth-adjacent tasks; decide by reading the full task.
Deduplicate task families (same template/asset lineage) before splitting control train/dev."""


def main() -> None:
    api = HfApi()
    files = api.list_repo_files(DATASET, repo_type="dataset", revision=REVISION)
    task_ids = sorted({f.split("/")[0] for f in files if f.endswith("/instruction.md")})
    rows = []
    for tid in task_ids:
        inst = Path(hf_hub_download(DATASET, f"{tid}/instruction.md", repo_type="dataset", revision=REVISION)).read_text(errors="replace")
        toml_path = f"{tid}/task.toml"
        meta = {}
        if toml_path in files:
            meta = tomllib.loads(Path(hf_hub_download(DATASET, toml_path, repo_type="dataset", revision=REVISION)).read_text())
        text = inst.lower()
        excl = sorted({p for p in EXCLUDE_TERMS if re.search(p, text)})
        rev = sorted({p for p in REVIEW_TERMS if re.search(p, text)})
        assets = sorted(f.split("/", 1)[1] for f in files if f.startswith(tid + "/") and "/environment/data/" in f)
        rows.append({
            "task_id": tid, "screen": "exclude" if excl else ("review" if rev else "candidate"),
            "exclude_terms": excl, "review_terms": rev, "instruction_chars": len(inst),
            "instruction_head": inst.strip().splitlines()[0][:160] if inst.strip() else "",
            "metadata": meta.get("metadata", {}), "agent_timeout_sec": meta.get("agent", {}).get("timeout_sec"),
            "environment": {k: v for k, v in meta.get("environment", {}).items() if k in ("cpus", "memory_mb", "storage_mb", "memory", "storage")},
            "data_assets": assets, "reviewer_decision": None, "reviewer_note": None,
        })
    out = REPO_ROOT / "manifests" / "control_review.jsonl"
    out.write_text("".join(json.dumps(r) + "\n" for r in rows))
    (REPO_ROOT / "manifests" / "control_rubric.md").write_text(RUBRIC + "\n")
    from collections import Counter
    print(json.dumps({"dataset": DATASET, "revision": REVISION, "n_tasks": len(rows), "screen": dict(Counter(r["screen"] for r in rows))}, indent=1))
    print(out)


if __name__ == "__main__":
    main()
