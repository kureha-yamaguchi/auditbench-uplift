"""Re-export: the single timestamp implementation lives in the stdlib-only grader package so that
the verifier container and the task builder can never disagree."""

from grader.timestamps import (  # noqa: F401
    LAB_TZ, PRECISION, classify_format, extract_raw_time, line_time, parse_annotation_time,
    parse_record_time, to_precision,
)
