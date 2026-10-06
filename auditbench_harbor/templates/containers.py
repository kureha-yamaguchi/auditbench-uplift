# Pinned by digest (manifest list for python:3.12-slim-bookworm, resolved 2026-10-03).
BASE_IMAGE = "python:3.12-slim-bookworm@sha256:54c85f3c47607a77f32adec749d3c81d1348bf25833671f512b26a9b6d778cb3"

ENV_DOCKERFILE = f"""FROM {BASE_IMAGE}
ENV DEBIAN_FRONTEND=noninteractive PIP_NO_CACHE_DIR=1
RUN apt-get update \\
 && apt-get install -y --no-install-recommends ripgrep jq tmux asciinema less procps \\
 && rm -rf /var/lib/apt/lists/*
RUN useradd --create-home --uid 1000 --shell /bin/bash agent
WORKDIR /app
COPY audit.log /app/audit.log
RUN chown root:root /app/audit.log && chmod 0444 /app/audit.log \\
 && mkdir -p /app/scratch && chown -R agent:agent /app/scratch \\
 && chown root:root /app && chmod 1777 /app   # sticky: the agent can create findings.json but not delete/replace the log
"""

# The separate verifier image is built from tests/ (Harbor uses tests/ as the build context).
# It owns the private manifest and a private copy of the log slice; the agent never sees it.
TESTS_DOCKERFILE = f"""FROM {BASE_IMAGE}
RUN mkdir -p /app /tests /logs/verifier
COPY audit.log /app/audit.log
COPY test.sh ground_truth.json /tests/
COPY grader /tests/grader
WORKDIR /tests
"""

TEST_SH = """#!/bin/bash
# Grades /logs/artifacts/app/findings.json (or /app/findings.json in a shared verifier) against the
# private manifest. Writes /logs/verifier/reward.json = {"reward": R} and diagnostics.json.
set -u
cd /tests
exec python3 -m grader.verify
"""
