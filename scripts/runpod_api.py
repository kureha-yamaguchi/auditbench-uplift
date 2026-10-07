#!/usr/bin/env python
"""Minimal RunPod REST client used for automatic pod stop/start (needs RUNPOD_API_KEY).

    python scripts/runpod_api.py status <pod_id>
    python scripts/runpod_api.py stop <pod_id>      # idempotent; used by spend_guard and run scripts
    python scripts/runpod_api.py start <pod_id>
Everything else (creation, billing) goes through the RunPod MCP plugin.
"""
import json
import os
import sys
import urllib.error
import urllib.request

BASE = "https://rest.runpod.io/v1"


def _call(method: str, path: str) -> dict:
    key = os.environ.get("RUNPOD_API_KEY")
    if not key:
        raise SystemExit("RUNPOD_API_KEY not set")
    # Cloudflare in front of the RunPod API rejects urllib's default User-Agent (403, "error code: 1010").
    req = urllib.request.Request(f"{BASE}{path}", method=method, headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json",
                                                                          "User-Agent": "auditbench-uplift/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            body = r.read().decode() or "{}"
            return json.loads(body) if body.strip() else {}
    except urllib.error.HTTPError as e:
        return {"error": e.code, "detail": e.read().decode()[:300]}


def status(pod_id: str) -> dict:
    return _call("GET", f"/pods/{pod_id}")


def stop(pod_id: str) -> dict:
    return _call("POST", f"/pods/{pod_id}/stop")


def start(pod_id: str) -> dict:
    return _call("POST", f"/pods/{pod_id}/start")


def main() -> None:
    if len(sys.argv) != 3 or sys.argv[1] not in ("status", "stop", "start"):
        raise SystemExit(__doc__)
    out = {"status": status, "stop": stop, "start": start}[sys.argv[1]](sys.argv[2])
    print(json.dumps({k: out.get(k) for k in ("id", "desiredStatus", "costPerHr", "error", "detail")} if isinstance(out, dict) else out))


if __name__ == "__main__":
    main()
