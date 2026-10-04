#!/usr/bin/env bash
# Gate-B/C smoke checks that need a sandbox provider (not runnable on a machine without Docker/Modal).
#   bash scripts/smoke_test.sh docker   # local: oracle agent on two dev tasks, expects reward 1.0 and isolation
#   bash scripts/smoke_test.sh modal    # provider: same, plus network/no-network enforcement probe
# The model smoke (terminus-2 + Qwen) is scripts/run_baseline.sh with --n-tasks via a job config override.
set -euo pipefail
ENV=${1:-docker}
JOB=smoke-$ENV-$(date +%s)
harbor run -p tasks/dev --n-tasks 2 -a oracle --env "$ENV" --env-file .env --job-name "$JOB" -n 2 \
  --ak suppress_max_turns_warning=true
python - "$JOB" <<'PY'
import json, sys, pathlib
job = pathlib.Path("jobs") / sys.argv[1]
ok = True
for trial in sorted(p for p in job.iterdir() if p.is_dir()):
    r = json.loads((trial / "result.json").read_text())
    reward = (r.get("verifier_result") or {}).get("rewards", {}).get("reward")
    diag = trial / "verifier" / "diagnostics.json"
    print(trial.name, "reward", reward, "mode", r.get("verifier_environment_mode"), "diag", diag.exists())
    ok &= reward == 1.0 and r.get("verifier_environment_mode") == "separate"
print("SMOKE", "PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
PY
# Isolation probe: an agent that tries to read the verifier material and reach the network must fail.
cat > /tmp/auditbench_probe.sh <<'SH'
set +e
ls /tests /solution 2>&1 | head -3
cat /logs/verifier/reward.json 2>&1 | head -1
python3 - <<'P'
import socket
try:
    socket.create_connection(("1.1.1.1", 80), timeout=3); print("NETWORK REACHABLE (BAD)")
except Exception as e: print("network blocked:", type(e).__name__)
P
echo '[]' > /app/findings.json
SH
echo "Run the probe as a custom agent command in your provider and confirm: no /tests, no /solution, no reward file, network blocked."
