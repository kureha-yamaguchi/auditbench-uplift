"""Isolation probe agent (PLAN.md §3.6, §4 integration checks). Not a policy: it runs fixed shell probes inside the
agent sandbox as the task's agent user, records the results to <logs_dir>/probe.json, attempts to spoof the reward,
and writes an empty findings array so the separate verifier's reward shows whether spoofing had any effect.

    harbor run -p tasks/dev -a auditbench_harbor.probe_agent:IsolationProbe --env modal ...
"""
import json
import shlex
from pathlib import Path

from harbor.agents.base import BaseAgent
from harbor.environments.base import BaseEnvironment
from harbor.models.agent.context import AgentContext

PY_NET = (
    "import socket,urllib.request\n"
    "r={}\n"
    "for k,f in [('dns',lambda: socket.gethostbyname('modal.com')),"
    "('tcp_1.1.1.1:443',lambda: socket.create_connection(('1.1.1.1',443),5).close()),"
    "('https_example',lambda: urllib.request.urlopen('https://example.com',timeout=5).status)]:\n"
    "    try: r[k]='OPEN '+str(f())\n"
    "    except Exception as e: r[k]='blocked '+type(e).__name__\n"
    "print(r)"
)

PROBES = {
    "identity": "id; umask",
    "network": f"python3 -c {shlex.quote(PY_NET)}",
    "private_paths": "ls -la /tests /solution /logs/verifier 2>&1; ls -la /logs 2>&1",
    "private_files_search": "find / -xdev \\( -name ground_truth.json -o -name solve.sh -o -name task.toml "
                            "-o -name diagnostics.json -o -path '*grader*' \\) 2>/dev/null | head -20",
    "label_strings": "grep -rlsE 'supported_positive|negative_attack_file|target_id' / --exclude-dir=proc --exclude-dir=sys "
                     "--exclude-dir=usr --exclude-dir=lib --exclude-dir=__modal 2>/dev/null | head -20",
    "env_secrets": "env | grep -iE 'modal|token|secret|key|wandb|hf_|runpod|aws|api' | sed -E 's/=.{4}.*/=<redacted>/'",
    "log_readonly": "ls -ld /app /app/audit.log; sha256sum /app/audit.log; (echo x >> /app/audit.log) 2>&1; rm -f /app/audit.log 2>&1; "
                    "mv /app/audit.log /app/x 2>&1; sha256sum /app/audit.log",
    "writable": "touch /app/findings.json /app/scratch/t /tmp/t 2>&1 && echo writable_ok",
    "reward_spoof": "mkdir -p /logs/verifier 2>&1; echo '{\"reward\": 1.0}' > /logs/verifier/reward.json 2>&1; echo rc=$?",
    "resources": "nproc; free -m | head -2; df -h /app /tmp | tail -2; cat /sys/fs/cgroup/cpu.max /sys/fs/cgroup/memory.max 2>&1; "
                 "python3 -c 'b=bytearray(3*2**30); print(\"allocated 3 GiB\")' 2>&1 | tail -1",
    "tools": "which rg jq python3 tmux curl wget 2>&1",
}


class IsolationProbe(BaseAgent):
    @staticmethod
    def name() -> str:
        return "auditbench-isolation-probe"

    def version(self) -> str:
        return "1.0.0"

    async def setup(self, environment: BaseEnvironment) -> None:
        return

    async def run(self, instruction: str, environment: BaseEnvironment, context: AgentContext) -> None:
        out = {}
        for key, cmd in PROBES.items():
            r = await environment.exec(command=cmd, timeout_sec=120)
            out[key] = {"rc": r.return_code, "stdout": r.stdout, "stderr": r.stderr}
        await environment.exec(command="echo '[]' > /app/findings.json", timeout_sec=30)
        Path(self.logs_dir).mkdir(parents=True, exist_ok=True)
        (Path(self.logs_dir) / "probe.json").write_text(json.dumps(out, indent=1))
