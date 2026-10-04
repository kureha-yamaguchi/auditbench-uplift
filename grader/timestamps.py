"""Timezone-explicit timestamp handling for every AuditBench record format.

All times are reduced to *naive benchmark-local wall-clock* datetimes, which is the frame the
ground-truth annotations use:

* Lab Linux (epoch floats in edge and raw lines): converted with America/Chicago explicitly.
  Upstream used the host timezone; this module never does.
* Lab Windows ("1/13/2025 2:00:00 AM"): already local wall clock.
* OpTC ("2019-09-23 13:23:21"): already local wall clock.
* OpTC velox files ("2019-09-17T11:23:48.01-04:00"): wall clock as written; the offset is recorded
  but not applied, because the annotation frame is the as-written local time.
"""

from __future__ import annotations

import re
from datetime import datetime
from zoneinfo import ZoneInfo

LAB_TZ = ZoneInfo("America/Chicago")

_EPOCH = re.compile(r"^\d{9,11}(\.\d+)?$")
_WINDOWS = "%m/%d/%Y %I:%M:%S %p"
_ISO_SECOND = "%Y-%m-%d %H:%M:%S"
_ISO_MINUTE = "%Y-%m-%d %H:%M"
_EDGE_PREFIX = re.compile(r"^\((.*?)\)")
_AUDITD_MSG = re.compile(r"msg=audit\((\d+\.\d+):\d+\)")

PRECISION = {  # ground-truth precision per (dataset, task)
    ("lab", "lm"): "second",
    ("lab", "persistence"): "minute",
    ("lab", "exfiltration"): "minute",
    ("optc", "lm"): "second",
    ("optc", "persistence"): "second",
    ("optc", "exfiltration"): "second",
}


def classify_format(raw: str) -> str | None:
    raw = raw.strip()
    if _EPOCH.match(raw):
        return "epoch"
    if re.match(r"^\d{1,2}/\d{1,2}/\d{4} \d{1,2}:\d{2}:\d{2} [AP]M$", raw):
        return "windows"
    if re.match(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$", raw):
        return "iso"
    if re.match(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$", raw):
        return "iso_minute"
    if re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?[+-]\d{2}:\d{2}$", raw):
        return "iso_offset"
    return None


def parse_record_time(raw: str) -> datetime | None:
    """Parse any supported record timestamp into naive benchmark-local time."""
    raw = raw.strip()
    fmt = classify_format(raw)
    if fmt == "epoch":
        return datetime.fromtimestamp(float(raw), LAB_TZ).replace(tzinfo=None)
    if fmt == "windows":
        return datetime.strptime(raw, _WINDOWS)
    if fmt == "iso":
        return datetime.strptime(raw, _ISO_SECOND)
    if fmt == "iso_minute":
        return datetime.strptime(raw, _ISO_MINUTE)
    if fmt == "iso_offset":
        return datetime.fromisoformat(raw).replace(tzinfo=None)
    return None


def extract_raw_time(line: str, representation: str) -> str | None:
    """Pull the record timestamp string out of an edge or raw auditd line."""
    if representation == "raw":
        m = _AUDITD_MSG.search(line)
        return m.group(1) if m else None
    m = _EDGE_PREFIX.match(line)
    return m.group(1) if m else None


def line_time(line: str, representation: str) -> datetime | None:
    raw = extract_raw_time(line, representation)
    return parse_record_time(raw) if raw else None


def to_precision(dt: datetime, precision: str) -> str:
    if precision == "minute":
        return dt.strftime(_ISO_MINUTE)
    if precision == "second":
        return dt.strftime(_ISO_SECOND)
    raise ValueError(precision)


def parse_annotation_time(raw: str) -> tuple[datetime, str]:
    """Ground-truth timestamps are 'YYYY-MM-DD HH:MM' or 'YYYY-MM-DD HH:MM:SS'. Returns (dt, precision)."""
    raw = raw.strip()
    try:
        return datetime.strptime(raw, _ISO_SECOND), "second"
    except ValueError:
        return datetime.strptime(raw, _ISO_MINUTE), "minute"
