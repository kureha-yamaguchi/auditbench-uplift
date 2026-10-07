#!/usr/bin/env bash
# Stop the RunPod pod behind the auditbench cluster from the laptop (SkyPilot cannot stop RunPod pods). Billing stops;
# the pod and its container disk remain so it can be started again with scripts/runpod_api.py start <id> if its host
# still has free GPUs. Falls back to `sky down` (terminate) when the pod id cannot be determined.
set -euo pipefail
REPO=$(cd "$(dirname "$0")/.." && pwd)
CLUSTER=${CLUSTER:-auditbench}
set -a; . "$REPO/.env"; set +a
pid=$(sky status "$CLUSTER" --json 2>/dev/null | python3 -c 'import json,sys; c=json.load(sys.stdin); print((c[0].get("handle") or {}).get("instance_id","") if c else "")' 2>/dev/null || true)
if [ -n "$pid" ]; then
  python3 "$REPO/scripts/runpod_api.py" stop "$pid"
else
  echo "pod_stop: no pod id from sky status; terminating the cluster instead" >&2
  sky down "$CLUSTER" -y
fi
