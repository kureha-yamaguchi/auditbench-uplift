#!/usr/bin/env bash
# The evaluation environment is separate from all training dependencies.
set -euo pipefail
HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE="${SHARED_CYBER_EVALS_WORKSPACE:-$(dirname -- "$(dirname -- "$HERE")")/shared-cyber-evals}"
COMMAND="${1:---help}"
if [[ $# -gt 0 ]]; then shift; fi
case "$COMMAND" in
  prepare|preflight|run)
    exec uv run --locked --project "$HERE" cyber-eval "$COMMAND" --study "$HERE/study.json" --workspace "$WORKSPACE" "$@"
    ;;
  *)
    exec uv run --locked --project "$HERE" cyber-eval "$COMMAND" "$@"
    ;;
esac
