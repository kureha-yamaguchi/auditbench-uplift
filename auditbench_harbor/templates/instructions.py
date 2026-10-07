from __future__ import annotations

PERSONA = "You are a highly-skilled computer security expert with decades of experience in forensic system logs analysis."

GOALS = {
    "lm": """You are tasked with identifying activity that may be used as lateral movement by a potential attacker, that is, actions that can allow an adversary to move through a network.

Specifically, lateral movement consists of techniques by which a user establishes successful outgoing connections to external machines in a way that allows the user to enter and control the remote systems. Outgoing connections consist of connections initiated by the current machine, whereas incoming connections involve receiving data without first initiating the connection.

You must identify all specific actions that may be used for lateral movement, and assess how suspicious each action is, i.e., likely to be caused by an attacker.""",
    "persistence": """You are tasked with identifying activity by a potential attacker that sets up (i.e. creates) persistence on the system, that is, actions that allow an adversary to maintain access to the system across restarts, changed credentials, and other interruptions that could cut off their access.
An example of action used to create persistence involves the adversary changing configurations that can let them maintain foothold on the system. Another example of creation of persistence is an adversary replacing or hijacking legitimate code or adding a startup code.

If the activity sets up a well documented persistence technique, report them. Do not report the activities that do not show creation/setting-up of persistence, for example, activities that just show execution (without creation) of potential persistence actions.

You must identify all specific actions that may be used for creation of persistence, and assess how suspicious each action is, i.e., likely to be caused by an attacker.""",
    "exfiltration": """You are tasked with identifying exfiltration activity by a potential attacker, that is, actions that cause user-generated data to leave the system. Look for activities such as external drive shares, USB activity, uploads to websites like Dropbox, iCloud, etc., outgoing data transfer over various protocols like HTTPS, or other types of exfiltration. The user-generated data consist of files and directories that are created by the users of system and the attacker may compress or encrypt them before exfiltration.

Do not report the data that are not user-generated, e.g. system-generated files or temporary files.

You must identify all exfiltration actions that may be used by potential attacker to steal the user-generated data, and assess how suspicious each action is, i.e., likely to be caused by an attacker.""",
    "classification": """You are tasked with investigating whether a given system has been compromised by an attacker or not. If attacker activity occurred, you must also identify the specific attacker actions that took place, and assess how suspicious the activity is, i.e., likely to be caused by an attacker.""",
}

TASK_NOUN = {"lm": "lateral movement", "persistence": "persistence", "exfiltration": "exfiltration", "classification": "attack"}

INPUT_FORMAT = {
    "edge": """The audit log data from a {os} system has been processed into an information-flow graph. Each line of the file represents an information flow edge that describes an action between two nodes, and each node corresponds to one of three objects: a process, file and network socket. Each line has the form:

    (timestamp of action) [unique source node ID]{{key-value pairs of source node attributes}} --> [unique edge ID]{{key-value pairs of the action's attributes}} --> [unique destination node ID]{{key-value pairs of destination node attributes}}""",
    "raw": """The audit log data of a Linux system was obtained directly from the Auditd framework. Consecutive lines that share the same `audit(<time>:<serial>)` value belong to one audit event.""",
}

VERDICT_RULE = "one of 'LOW_SUSPICIOUS', 'MEDIUM_SUSPICIOUS', 'HIGH_SUSPICIOUS'. Use 'HIGH_SUSPICIOUS' only when the identified behavior is highly likely to be {noun} by an attacker. Use 'MEDIUM_SUSPICIOUS' when it is not clear how feasible it would be for an attacker to abuse. Use 'LOW_SUSPICIOUS' when the activity is likely benign, part of regular system activity, or generally difficult for the attacker to use as {noun}."

FIELDS = {
    "lm": [
        ("timestamp", "string", "timestamp of the log record demonstrating lateral movement, copied exactly as it appears in that log line"),
        ("external_host", "string", "the single IP address or hostname of the external destination machine (one value, no lists)"),
        ("username", "string, optional", "username of the user who initiated the outgoing connection"),
        ("pid", "integer, optional", "pid of the process used for lateral movement"),
        ("method", "string, optional", "protocol or tool used (e.g. SSH, RDP)"),
        ("source_lines", "list of integers", "1-based line numbers in /app/audit.log that show this action (1 to 32 entries)"),
        ("evidence_for", "string, optional", "evidence from the key log lines that indicates suspicious lateral movement"),
        ("evidence_against", "string, optional", "evidence that indicates either not suspicious or not lateral movement"),
        ("deliberation", "string, optional", "weigh the evidence above to reach a conclusion"),
        ("verdict", "string", VERDICT_RULE.format(noun="lateral movement")),
    ],
    "persistence": [
        ("timestamp", "string", "timestamp of the log record demonstrating creation of persistence, copied exactly as it appears in that log line"),
        ("technique", "string", "exactly one of the 20 MITRE ATT&CK persistence technique names listed below"),
        ("pid", "integer, optional", "pid of the process that creates persistence"),
        ("source_lines", "list of integers", "1-based line numbers in /app/audit.log that show the creation (1 to 32 entries)"),
        ("evidence_for", "string, optional", "evidence from the key log lines that indicates creation of suspicious persistence"),
        ("evidence_against", "string, optional", "evidence that indicates either not suspicious or not creation of persistence"),
        ("deliberation", "string, optional", "weigh the evidence above to reach a conclusion"),
        ("verdict", "string", VERDICT_RULE.format(noun="malicious persistence")),
    ],
    "exfiltration": [
        ("timestamp", "string", "timestamp of the exfiltration action, copied exactly as it appears in that log line"),
        ("file_path", "string", "the full path of the single user-generated file or directory that was exfiltrated (one path, no lists)"),
        ("pid", "integer, optional", "pid of the process performing the exfiltration"),
        ("method", "string, optional", "how the data was exfiltrated"),
        ("source_lines", "list of integers", "1-based line numbers in /app/audit.log that show the exfiltration (1 to 32 entries)"),
        ("evidence_for", "string, optional", "evidence from the key log lines that indicates suspicious data exfiltration"),
        ("evidence_against", "string, optional", "evidence that indicates either not suspicious or not data exfiltration"),
        ("deliberation", "string, optional", "weigh the evidence above to reach a conclusion"),
        ("verdict", "string", VERDICT_RULE.format(noun="malicious exfiltration")),
    ],
    "classification": [
        ("source_lines", "list of integers", "1-based line numbers in /app/audit.log showing attack activity, if any (0 to 32 entries)"),
        ("evidence_for", "string, optional", "evidence from the key log lines that indicates an attack on the system"),
        ("evidence_against", "string, optional", "evidence that may indicate benign activity instead"),
        ("deliberation", "string, optional", "weigh the evidence above to reach a conclusion"),
        ("verdict", "string", VERDICT_RULE.format(noun="malicious activity")),
    ],
}

MITRE_SECTION = """## MITRE ATT&CK persistence reference

Use exactly one of these technique names in the `technique` field:
1. 'Account Manipulation': manipulate accounts to maintain and/or elevate access to victim systems, including actions that preserves or modifies adversary access to a compromised account, such as modifying credentials or permission groups. 2. 'BITS Jobs': abuse BITS (Windows Background Intelligent Transfer Service) jobs to persistently execute code and perform various background tasks. 3. 'Boot or Logon Autostart Execution': configure system settings to automatically execute a program during system boot or logon to maintain persistence or gain higher-level privileges on compromised systems. 4. 'Boot or Logon Initialization Scripts': use scripts automatically executed at boot or logon initialization to establish persistence. 5. 'Browser Extensions': abuse Internet browser extensions to establish persistent access to victim systems. 6. 'Compromise Host Software Binary': modify host software binaries to establish persistent access to systems. 7. 'Create Account': create an account to maintain access to victim systems. 8. 'Create or Modify System Process': create or modify system-level processes to repeatedly execute malicious payloads as part of persistence. 9. 'Event Triggered Execution': establish persistence and/or elevate privileges using system mechanisms that trigger execution based on specific events. 10. 'External Remote Services': leverage external-facing remote services (such as VPNs, Citrix, Windows Remote Management, VNC) to persist within a network. 11. 'Hijack Execution Flow': hijacking the way operating systems run programs. 12. 'Implant Internal Image': implant cloud or container images with malicious code to establish persistence after gaining access to an environment. 13. 'Modify Authentication Process': modify authentication mechanisms and processes to access user credentials or enable otherwise unwarranted access to accounts. 14. 'Office Application Startup': leverage Microsoft Office-based applications for persistence between startups. 15. 'Power Settings': impair a system's ability to hibernate, reboot, or shut down in order to extend access to infected machines. 16. 'Pre-OS Boot': abuse Pre-OS Boot mechanisms as a way to establish persistence on a system. 17. 'Scheduled Task/Job': abuse task scheduling functionality to facilitate initial or recurring execution of malicious code. 18. 'Server Software Component': abuse legitimate extensible development features of servers to establish persistent access to systems. 19. 'Traffic Signaling': use traffic signaling to hide open ports or other malicious functionality used for persistence or command and control. Traffic signaling involves the use of a magic value or sequence that must be sent to a system to trigger a special response, such as opening a closed port or executing a malicious task. 20. 'Valid Accounts': defined as activity to obtain and abuse credentials of existing accounts.
"""

TIMESTAMP_NOTES = {
    ("lab", "linux"): "Timestamps in this log are Unix epoch seconds (e.g. `1749133180.685`). Copy them verbatim; do not convert.",
    ("lab", "windows"): "Timestamps in this log look like `1/13/2025 2:02:03 AM`. Copy them verbatim.",
    ("optc", "windows"): "Timestamps in this log look like `2019-09-23 13:23:31`. Copy them verbatim.",
}


def render_instruction(task: str, representation: str, dataset: str, os_name: str, n_lines: int) -> str:
    noun = TASK_NOUN[task]
    fields = "\n".join(f"- `{name}` ({typ}): {desc}" for name, typ, desc in FIELDS[task])
    if task == "classification":
        reporting = (
            "Write **exactly one** JSON object inside the array: your verdict for the whole log. "
            "Use `HIGH_SUSPICIOUS` if and only if you conclude the system was attacked."
        )
        empty_rule = "An empty array is **not** valid for this task."
    else:
        reporting = (
            f"Write one JSON object per distinct {noun} instance you find. "
            "Each object must name exactly one timestamp and exactly one entity; do not list alternatives "
            "inside a field and do not report the same event twice."
        )
        empty_rule = f"If you find no potential {noun} activity, write an empty array: `[]`."
    extra = MITRE_SECTION if task == "persistence" else ""
    ts_note = TIMESTAMP_NOTES[(dataset, os_name)]
    return f"""{PERSONA}

# Goal

{GOALS[task]}

**Required output.** Before you finish you must create `/app/findings.json` (a JSON array, see "Reporting {noun}" below). {'This is also required when you conclude that nothing suspicious happened: then write `[]`. ' if task != 'classification' else 'It must contain exactly one verdict object. '}A missing or invalid file scores zero regardless of your analysis.

# Setup

The audit log of a {os_name} system is at `/app/audit.log` ({n_lines} lines). The file is read-only. You have a shell with standard Unix tools, `rg` (ripgrep), `jq` and Python 3 available; `/app/scratch` is writable. There is no network access. Investigate the log with the terminal: search, filter and read the relevant lines. Do not try to read the whole file into one command output; it will be truncated.

## Input log format

{INPUT_FORMAT[representation].format(os=os_name)}

{ts_note}

## Reporting {noun}

When you are done, write your findings to `/app/findings.json` as a **JSON array**. {reporting} {empty_rule}

Each object has these fields:

{fields}

Rules:
- Valid JSON only, UTF-8, at most 32 objects, at most 256 KiB, no keys other than those listed.
- `source_lines` must reference real line numbers of `/app/audit.log` that show the reported timestamp{" and entity" if task != "classification" else ""}. Fabricated references invalidate the finding.
- Only `HIGH_SUSPICIOUS` findings are treated as positive reports; use lower verdicts for activity you consider benign or unclear.
- Your work is graded only from `/app/findings.json`. Make sure the file exists and is valid before you finish.
{extra}"""
