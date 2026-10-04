Control-pool rubric (frozen before main runs):
EXCLUDE: offensive or defensive security content (attack/defence, malware, vulnerabilities, exploitation,
         CTF, forensics, SIEM/audit-log analysis, credential attacks), anything sharing assets or
         solutions with CyberGym, ExploitBench, AuditBench or ExCyTIn-Bench.
PREFER:  routine text/file transformation, data manipulation, shell tasks with comparable
         read/search/write behaviour, resource needs within 1 CPU / 1 GiB or an explicitly recorded exception.
REVIEW:  generic logs, crypto utilities, networking, auth-adjacent tasks; decide by reading the full task.
Deduplicate task families (same template/asset lineage) before splitting control train/dev.
