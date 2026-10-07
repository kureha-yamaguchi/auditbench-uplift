#!/usr/bin/env bash
# Provision the `auditbench` cluster on the first RunPod Secure Cloud data centre that has a free 4-GPU node
# (PLAN.md §8.1, amendment 2026-10-07). Each attempt runs the GPU ladder in configs/skypilot/runpod-4xh200.yaml
# (ordered: H200 > H100-SXM > H100-NVL > H100 > A100-80GB) against ONE data centre and that data centre's network
# volume; data centres are tried in order and the loop repeats until a launch succeeds. RunPod network volumes are
# bound to a data centre, so a volume is created on demand for each new one (300 GB, about $21/month); volumes this
# script created but did not end up using are deleted when it exits. One cluster name, one launch at a time: no
# risk of two pods billing.
#   bash scripts/launch_ladder.sh                      # then: sky exec -c auditbench --env-file .env -- bash scripts/phase.sh smoke
#   DCS="EU-FR-1 US-CA-2" SLEEP=60 bash scripts/launch_ladder.sh
# A failure that is not a capacity failure stops the loop; if a pod exists by then it is stopped (billing off).
set -euo pipefail
REPO=$(cd "$(dirname "$0")/.." && pwd)
SPEC="$REPO/configs/skypilot/runpod-4xh200.yaml"
GEN="$REPO/runs_local/sky/generated"; mkdir -p "$GEN"
# Only data centres with network-volume support (RunPod GraphQL dataCenters.storageSupport, checked 2026-10-07) that
# listed H200/H100 stock; the existing EU-FR-1 volume goes first.
DCS=${DCS:-"EU-FR-1 US-CA-2 AP-JP-1 US-NE-1 EUR-IS-3 CA-MTL-1"}
SLEEP=${SLEEP:-30}
CLUSTER=auditbench

country() {
  case "$1" in
    EU-FR-*) echo FR;; US-*) echo US;; CA-*) echo CA;; AP-JP-*) echo JP;; AP-IN-*) echo IN;;
    EUR-IS-*) echo IS;; EU-NL-*) echo NL;; EU-RO-*) echo RO;; EUR-NO-*) echo NO;;
    *) echo "launch_ladder: no country code for data centre $1" >&2; return 1;;
  esac
}
volume_for() { [ "$1" = EU-FR-1 ] && echo auditbench-uplift-durable || echo "auditbench-uplift-$(echo "$1" | tr '[:upper:]' '[:lower:]')"; }
runpod_volume_names() {  # volumes that already exist on the RunPod account (adopt rather than create)
  local key; key=$(grep '^RUNPOD_API_KEY=' "$REPO/.env" | cut -d= -f2- | sed 's/[[:space:]]*#.*//; s/^"//; s/"$//')
  curl -sf -H "Authorization: Bearer $key" https://rest.runpod.io/v1/networkvolumes | python3 -c 'import json,sys; print("\n".join(v["name"] for v in json.load(sys.stdin)))' 2>/dev/null || true
}

USED=""         # volume of the successful launch
cleanup() {
  # Cancel any launch request still running on the SkyPilot API server (killing the client does not).
  for id in $(sky api status 2>/dev/null | awk '/sky.launch/{print $1}'); do sky api cancel "$id" >/dev/null 2>&1 || true; done
  # Delete ladder volumes that have never been used by any cluster (LAST_USE "-"): they hold nothing. The EU-FR-1
  # volume and the one the successful launch attached are always kept.
  # columns: NAME TYPE INFRA SIZE USER WORKSPACE AGE STATUS LAST_USE USED_BY
  sky volumes ls 2>/dev/null | awk 'NR>1 && $1 ~ /^auditbench-uplift-/ && $9 == "-" {print $1}' | while read -r v; do
    [ "$v" = auditbench-uplift-durable ] || [ "$v" = "$USED" ] && continue
    echo "launch_ladder: deleting never-used volume $v"; sky volumes delete "$v" -y >/dev/null 2>&1 || true
  done
}
trap cleanup EXIT

ensure_volume() {  # $1 data centre, $2 country, $3 volume name; returns 1 if the data centre cannot host a volume
  sky volumes ls 2>/dev/null | awk 'NR>1{print $1}' | grep -qx "$3" && return 0
  # SkyPilot names the RunPod volume "<name>-<suffix>", so match on the prefix.
  if runpod_volume_names | grep -qE "^$3(-|$)"; then
    sky volumes apply --name "$3" --infra "runpod/$2/$1" --type runpod-network-volume --size 300 --use-existing -y >/dev/null
  else
    echo "$(date -u +%FT%TZ) creating network volume $3 in $1 (300 GB, ~\$21/month while it exists)"
    sky volumes apply --name "$3" --infra "runpod/$2/$1" --type runpod-network-volume --size 300 -y >/dev/null || true
    # `apply` can return success without RunPod creating anything (data centres without storage support).
    if ! runpod_volume_names | grep -qE "^$3(-|$)"; then
      echo "$(date -u +%FT%TZ) $1 cannot host a network volume; skipping it"
      sky volumes delete "$3" -y >/dev/null 2>&1 || true
      return 1
    fi
  fi
}

round=0
while true; do
  round=$((round + 1))
  for dc in $DCS; do
    cc=$(country "$dc"); vol=$(volume_for "$dc")
    ensure_volume "$dc" "$cc" "$vol" || continue
    yaml="$GEN/$dc.yaml"
    sed -e "s|runpod/FR/EU-FR-1|runpod/$cc/$dc|" -e "s|auditbench-uplift-durable|$vol|" -e "s|^workdir: \.$|workdir: $REPO|" "$SPEC" > "$yaml"
    log="$GEN/$dc.launch.log"
    echo "$(date -u +%FT%TZ) round $round: trying $dc (volume $vol)"
    if sky launch -c "$CLUSTER" "$yaml" --env-file "$REPO/.env" -y > "$log" 2>&1; then
      USED="$vol"
      echo "$(date -u +%FT%TZ) cluster $CLUSTER is up on $dc with volume $vol; setup finished. Log: $log"
      sky status "$CLUSTER" 2>/dev/null | tail -n +2 || true
      exit 0
    fi
    if grep -qE "ResourcesUnavailableError|VolumeNotFoundError" "$log"; then
      continue   # capacity only (or the volume is not visible yet); next data centre
    fi
    echo "$(date -u +%FT%TZ) non-capacity failure on $dc; see $log" >&2
    if sky status "$CLUSTER" 2>/dev/null | grep -qE "^$CLUSTER\s"; then
      echo "launch_ladder: a pod exists; stopping it so it does not bill idle" >&2
      # SkyPilot cannot stop RunPod pods ("Stopping is currently not supported for runpod"); use the RunPod API.
      pid=$(sky status "$CLUSTER" --json 2>/dev/null | python3 -c "import json,sys; print(json.load(sys.stdin)[0]['handle'].get('instance_id',''))" 2>/dev/null || true)
      [ -n "$pid" ] && (set -a; . "$REPO/.env"; set +a; python3 "$REPO/scripts/runpod_api.py" stop "$pid") || sky down "$CLUSTER" -y >/dev/null 2>&1 || true
    fi
    exit 1
  done
  sleep "$SLEEP"
done
