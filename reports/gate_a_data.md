# Gate A: data, provenance, labels, splits

Status: generated and checked locally on the AuditBench checkout `369ad441f287`; model-blind.

- Inventory: 129 files, 69 distinct contents, 20 byte-identical groups,
  51 dataset-qualified scenario names; nominal chunks {'lab edge': {'classification_files': 10, 'investigation_files': 30, 'nominal_chunks': 129}, 'lab raw': {'classification_files': 8, 'investigation_files': 25, 'nominal_chunks': 126}, 'optc edge': {'classification_files': 15, 'investigation_files': 41, 'nominal_chunks': 482}}; timestamp parse failures 0,
  non-monotonic records 0. All times are reduced with explicit timezones (`grader/timestamps.py`).
- Provenance: 183 edges, 40 groups (plan's preliminary estimate was 49 components before campaign review; OpTC
  same-host-same-day links reduce it further).
- Split: see `splits/README.md`.
- Labels: every train/dev annotation unit is `supported_positive`; five OpTC lm-scenario2 hosts (multicast/broadcast/link-local)
  are `ambiguous` and sit in the sealed test split; Lab lm-scenario3 has no file and a placeholder entity (unplaced).
- OpTC LM uses the unique-host convention (records merged by external host); persistence records with several technique names
  become one target unit per technique sharing the candidate timestamps.

Resolved 2026-10-06 (`manifests/label_review.meta.json`): investigator accepted all train/dev targets without an itemised
review or drawn negative sample; weak edges stay unused; the exfiltration train cell stays as is (limitation).

Original open items: human review of `manifests/labels/{train,dev}.jsonl` evidence lines and of the
negative attack-file windows sample; decision on OpTC campaign-day (weak) edges; decision on the thin exfiltration train cell.
