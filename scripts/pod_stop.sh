#!/usr/bin/env bash
# Stop the RunPod pod behind the auditbench cluster from the laptop (SkyPilot cannot stop RunPod pods). Billing stops;
# the pod and its container disk remain so it can be started again with scripts/runpod_api.py start <id> if its host
# still has free GPUs. The pod is found through the RunPod API by SkyPilot's naming ("<cluster>-<hash>-head").
# Never falls back to `sky down`: terminating loses the node for good (2026-10-07).
set -euo pipefail
REPO=$(cd "$(dirname "$0")/.." && pwd)
CLUSTER=${CLUSTER:-auditbench}
set -a; . "$REPO/.env"; set +a
ids=$(curl -sf -A "auditbench-uplift/1.0" -H "Authorization: Bearer $RUNPOD_API_KEY" https://rest.runpod.io/v1/pods \
  | python3 -c "import json,sys; print(' '.join(p['id'] for p in json.load(sys.stdin) if p['name'].startswith('$CLUSTER-') and p['desiredStatus']=='RUNNING'))")
if [ -z "$ids" ]; then echo "pod_stop: no running pod named $CLUSTER-* on the RunPod account"; exit 0; fi
for id in $ids; do
  echo "pod_stop: stopping $id"
  python3 "$REPO/scripts/runpod_api.py" stop "$id"
done
