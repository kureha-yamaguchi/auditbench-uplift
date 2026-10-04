"""Frozen normalisation of timestamps and entities for matching. Do not loosen after seeing model errors."""

from __future__ import annotations

import re

from .timestamps import parse_record_time, to_precision

_BACKSLASHES = re.compile(r"\\{2,}")


def norm_timestamp(raw: str, precision: str) -> str | None:
    dt = parse_record_time(raw)
    return to_precision(dt, precision) if dt else None


def norm_host(value: str) -> str:
    v = value.strip().lower().strip("[]")
    return v.rstrip(".")


def norm_technique(value: str) -> str:
    return " ".join(value.strip().lower().replace("-", " ").split())


def norm_path(value: str, case_insensitive: bool) -> str:
    v = _BACKSLASHES.sub("\\\\", value.strip().strip("'\""))
    return v.lower() if case_insensitive else v


def norm_entity(kind: str, value: str, case_insensitive_paths: bool) -> str:
    if kind == "host":
        return norm_host(value)
    if kind == "technique":
        return norm_technique(value)
    if kind == "path":
        return norm_path(value, case_insensitive_paths)
    raise ValueError(kind)
