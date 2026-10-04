"""Strict parsing and schema validation of `/app/findings.json`.

Any violation makes the whole output invalid (reward 0). Rules are frozen here; see PLAN.md §5.1.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from .timestamps import classify_format

MAX_BYTES = 256 * 1024
MAX_FINDINGS = 32
MAX_SOURCE_LINES = 32
MAX_STRING = 2000
VERDICTS = ("LOW_SUSPICIOUS", "MEDIUM_SUSPICIOUS", "HIGH_SUSPICIOUS")
HIGH = "HIGH_SUSPICIOUS"

ENTITY_KEY = {"lm": "external_host", "persistence": "technique", "exfiltration": "file_path"}
REQUIRED = {
    "lm": ("timestamp", "external_host", "source_lines", "verdict"),
    "persistence": ("timestamp", "technique", "source_lines", "verdict"),
    "exfiltration": ("timestamp", "file_path", "source_lines", "verdict"),
    "classification": ("verdict", "source_lines"),
}
OPTIONAL = {
    "lm": ("username", "pid", "method", "evidence_for", "evidence_against", "deliberation"),
    "persistence": ("pid", "evidence_for", "evidence_against", "deliberation"),
    "exfiltration": ("pid", "method", "evidence_for", "evidence_against", "deliberation"),
    "classification": ("evidence_for", "evidence_against", "deliberation"),
}
_HOST = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.:\-\[\]]*$")
_LIST_SEPARATORS = re.compile(r"[,;|\n\r\t]| or | and ")
_TECHNIQUE_SEPARATORS = re.compile(r"[,;|\n\r\t]")


class SchemaError(ValueError):
    pass


@dataclass
class Finding:
    index: int
    verdict: str
    source_lines: list[int]
    timestamp: str | None = None
    entity: str | None = None
    extra: dict = field(default_factory=dict)

    @property
    def is_high(self) -> bool:
        return self.verdict == HIGH


def _reject_duplicate_keys(pairs):
    obj = {}
    for k, v in pairs:
        if k in obj:
            raise SchemaError(f"duplicate JSON key {k!r}")
        obj[k] = v
    return obj


def _reject_constant(name):
    raise SchemaError(f"non-finite JSON constant {name}")


def read_output_file(path: Path) -> bytes:
    if path.is_symlink():
        raise SchemaError("output is a symlink")
    if not path.is_file():
        raise SchemaError("output missing or not a regular file")
    size = path.stat().st_size
    if size == 0:
        raise SchemaError("output is empty")
    if size > MAX_BYTES:
        raise SchemaError(f"output exceeds {MAX_BYTES} bytes")
    return path.read_bytes()


def parse_json(data: bytes):
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as e:
        raise SchemaError(f"output is not UTF-8: {e}") from e
    try:
        return json.loads(text, object_pairs_hook=_reject_duplicate_keys, parse_constant=_reject_constant)
    except json.JSONDecodeError as e:
        raise SchemaError(f"invalid JSON: {e.msg} at line {e.lineno}") from e


def _check_string(name: str, value, required: bool = True) -> str | None:
    if value is None and not required:
        return None
    if not isinstance(value, str):
        raise SchemaError(f"{name} must be a string")
    if len(value) > MAX_STRING:
        raise SchemaError(f"{name} exceeds {MAX_STRING} characters")
    return value


def _check_entity(task: str, value: str) -> str:
    v = value.strip()
    if not v:
        raise SchemaError(f"{ENTITY_KEY[task]} is empty")
    separators = _TECHNIQUE_SEPARATORS if task == "persistence" else _LIST_SEPARATORS
    if separators.search(v):
        raise SchemaError(f"{ENTITY_KEY[task]} must name exactly one candidate")
    if task == "lm" and not _HOST.match(v):
        raise SchemaError("external_host must be a single IP address or hostname")
    return v


def _check_source_lines(value, n_lines: int, allow_empty: bool) -> list[int]:
    if not isinstance(value, list):
        raise SchemaError("source_lines must be a list of integers")
    if not value and not allow_empty:
        raise SchemaError("source_lines must reference at least one log line")
    if len(value) > MAX_SOURCE_LINES:
        raise SchemaError(f"source_lines exceeds {MAX_SOURCE_LINES} entries")
    out = []
    for x in value:
        if isinstance(x, bool) or not isinstance(x, int):
            raise SchemaError("source_lines entries must be integers")
        if x < 1 or x > n_lines:
            raise SchemaError(f"source line {x} is outside 1..{n_lines}")
        out.append(x)
    if len(set(out)) != len(out):
        raise SchemaError("source_lines contains duplicates")
    return out


def validate(obj, task: str, n_lines: int) -> list[Finding]:
    if not isinstance(obj, list):
        raise SchemaError("top-level value must be a JSON array")
    if len(obj) > MAX_FINDINGS:
        raise SchemaError(f"more than {MAX_FINDINGS} findings")
    if task == "classification" and len(obj) != 1:
        raise SchemaError("classification requires exactly one verdict object")
    required, optional = REQUIRED[task], OPTIONAL[task]
    findings = []
    for i, item in enumerate(obj):
        if not isinstance(item, dict):
            raise SchemaError(f"finding {i} is not an object")
        missing = [k for k in required if k not in item]
        if missing:
            raise SchemaError(f"finding {i} missing {missing}")
        unknown = [k for k in item if k not in required and k not in optional]
        if unknown:
            raise SchemaError(f"finding {i} has unknown keys {unknown}")
        verdict = item["verdict"]
        if verdict not in VERDICTS:
            raise SchemaError(f"finding {i} verdict {verdict!r} not in {list(VERDICTS)}")
        lines = _check_source_lines(item["source_lines"], n_lines, allow_empty=(task == "classification"))
        extra = {}
        for k in optional:
            if k in item:
                if k == "pid":
                    if item[k] is not None and (isinstance(item[k], bool) or not isinstance(item[k], int) or item[k] < 0):
                        raise SchemaError(f"finding {i} pid must be a non-negative integer or null")
                    extra[k] = item[k]
                else:
                    extra[k] = _check_string(f"finding {i} {k}", item[k], required=False)
        f = Finding(i, verdict, lines, extra=extra)
        if task != "classification":
            ts = _check_string(f"finding {i} timestamp", item["timestamp"]).strip()
            if classify_format(ts) is None:
                raise SchemaError(f"finding {i} timestamp {ts!r} is not a recognised log timestamp format")
            f.timestamp = ts
            f.entity = _check_entity(task, _check_string(f"finding {i} {ENTITY_KEY[task]}", item[ENTITY_KEY[task]]))
        findings.append(f)
    return findings


def load_findings(path: Path, task: str, n_lines: int) -> list[Finding]:
    """Read, parse and validate. Raises SchemaError on any violation."""
    return validate(parse_json(read_output_file(path)), task, n_lines)
