"""Scan `data/input` and describe every scenario file: identity, hashes, timestamps, labels."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .paths import DATASETS, data_input_dir
from .timestamps import classify_format, extract_raw_time, parse_record_time

# edge_2024-11-27T14-04-to-2024-11-27T14-10_lm-scenario2.log
# edge_2019-09-23T13-23-21-to-2019-09-23T13-23-41_h201_lm-scenario1.log
_NAME = re.compile(
    r"^(?P<rep>edge|raw)_(?P<start>\d{4}-\d{2}-\d{2}T\d{2}-\d{2}(?:-\d{2})?)-to-"
    r"(?P<end>\d{4}-\d{2}-\d{2}T\d{2}-\d{2}(?:-\d{2})?)_(?:(?P<host>h\d{3})_)?(?P<scenario>[A-Za-z0-9-]+)\.log$"
)


@dataclass
class FileRecord:
    rel_path: str
    dataset: str
    task: str
    representation: str
    filename: str
    scenario: str
    scenario_key: str  # dataset-qualified: "lab/lm-scenario7", "optc/h501_lm-scenario5"
    host: str | None
    label: str  # "attack" | "benign"
    os: str
    window_start: str
    window_end: str
    sha256: str
    bytes: int
    lines: int
    ts_formats: list[str] = field(default_factory=list)
    first_time: str | None = None
    last_time: str | None = None
    parse_failures: int = 0
    nonmonotonic: int = 0


def _parse_name(name: str) -> dict:
    m = _NAME.match(name)
    if not m:
        raise ValueError(f"unrecognised scenario filename: {name}")
    return m.groupdict()


def _filename_time(token: str) -> str:
    date, clock = token.split("T")
    parts = clock.split("-")
    clock = ":".join(parts) if len(parts) == 3 else ":".join(parts) + ":00"
    return f"{date} {clock}"


def scan_file(path: Path, dataset: str, task: str) -> FileRecord:
    meta = _parse_name(path.name)
    rep = meta["rep"]
    sha = hashlib.sha256()
    formats: set[str] = set()
    first = last = prev = None
    failures = nonmono = lines = 0
    with path.open("rb") as fh:
        for raw_line in fh:
            sha.update(raw_line)
            lines += 1
            line = raw_line.decode("utf-8", errors="replace")
            raw_ts = extract_raw_time(line, rep)
            dt = parse_record_time(raw_ts) if raw_ts else None
            if dt is None:
                failures += 1
                continue
            formats.add(classify_format(raw_ts))
            first = first or dt
            last = dt
            if prev is not None and dt < prev:
                nonmono += 1
            prev = dt
    scenario = meta["scenario"]
    host = meta["host"]
    key = f"{dataset}/{host + '_' if host else ''}{scenario}"
    is_attack = "benign" not in scenario
    os_name = "windows" if dataset == "optc" or "windows" in formats else "linux"
    return FileRecord(
        rel_path=str(path.relative_to(data_input_dir())),
        dataset=dataset,
        task=task,
        representation=rep,
        filename=path.name,
        scenario=scenario,
        scenario_key=key,
        host=host,
        label="attack" if is_attack else "benign",
        os=os_name,
        window_start=_filename_time(meta["start"]),
        window_end=_filename_time(meta["end"]),
        sha256=sha.hexdigest(),
        bytes=path.stat().st_size,
        lines=lines,
        ts_formats=sorted(formats),
        first_time=first.isoformat(sep=" ") if first else None,
        last_time=last.isoformat(sep=" ") if last else None,
        parse_failures=failures,
        nonmonotonic=nonmono,
    )


def scan_all() -> list[FileRecord]:
    root = data_input_dir()
    records = []
    for dataset in DATASETS:
        for task_dir in sorted((root / dataset).glob("task_*")):
            task = task_dir.name.removeprefix("task_")
            for log in sorted(task_dir.glob("*/*.log")):
                records.append(scan_file(log, dataset, task))
    return records


def write_inventory(records: list[FileRecord], out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps([asdict(r) for r in records], indent=1) + "\n")


def load_inventory(path: Path) -> list[FileRecord]:
    return [FileRecord(**r) for r in json.loads(path.read_text())]


def summarize(records: list[FileRecord]) -> dict:
    """Counts matching PLAN.md §2 (files, nominal chunks, duplicate groups, scenario names)."""
    from collections import Counter

    chunk_size = {"edge": 400, "raw": 1000}
    by_source: dict[str, Counter] = {}
    for r in records:
        key = f"{r.dataset} {r.representation}"
        c = by_source.setdefault(key, Counter())
        if r.task == "classification":
            c["classification_files"] += 1
        else:
            c["investigation_files"] += 1
            c["nominal_chunks"] += -(-r.lines // chunk_size[r.representation])
    hashes = Counter(r.sha256 for r in records)
    return {
        "files": len(records),
        "distinct_contents": len(hashes),
        "byte_identical_groups": sum(1 for n in hashes.values() if n > 1),
        "scenario_keys": len({r.scenario_key for r in records}),
        "by_source": {k: dict(v) for k, v in sorted(by_source.items())},
        "parse_failures_total": sum(r.parse_failures for r in records),
        "nonmonotonic_total": sum(r.nonmonotonic for r in records),
    }
