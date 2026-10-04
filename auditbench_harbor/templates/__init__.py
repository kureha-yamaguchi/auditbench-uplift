"""Instruction and container templates for AuditBench-Agent tasks.

The investigation goals, log-format descriptions and the MITRE reference list are the upstream v2
prompt texts (inference/prompt_template/*_v2.py at commit 369ad441), adapted from a single-shot
prompt to a terminal task: the log is a searchable file, and findings are written as a JSON file.
"""

from .instructions import render_instruction  # noqa: F401
from .containers import ENV_DOCKERFILE, TESTS_DOCKERFILE, TEST_SH  # noqa: F401
