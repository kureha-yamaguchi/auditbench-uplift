"""`auditbench-harbor`: inventory -> provenance -> split -> labels -> units -> build -> check."""

from __future__ import annotations

import argparse
import json
import platform
import sys
from collections import Counter
from pathlib import Path

from . import SCHEMA_VERSION
from .paths import MANIFESTS_DIR, REPO_ROOT, SPLITS_DIR, TASKS_DIR, auditbench_dir, git_state

INVENTORY = MANIFESTS_DIR / "inventory.json"
VERSIONS = MANIFESTS_DIR / "versions.json"
GROUPS = MANIFESTS_DIR / "groups.json"
EDGES = SPLITS_DIR / "group_edges.jsonl"
LABELS_DIR = MANIFESTS_DIR / "labels"
UNITS_DIR = MANIFESTS_DIR / "units"
SEALED_TEST_NOTE = "test is sealed: pass --allow-test and set AUDITBENCH_ALLOW_TEST=1 to build or inspect it"


def _load_json(p: Path):
    return json.loads(p.read_text())


def _dump(obj, p: Path) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, indent=1, default=str) + "\n")


def cmd_inventory(args) -> None:
    from importlib.metadata import version
    from .ground_truth import annotation_file_hashes
    from .inventory import scan_all, summarize, write_inventory

    records = scan_all()
    write_inventory(records, INVENTORY)
    summary = summarize(records)
    versions = {
        "schema_version": SCHEMA_VERSION,
        "auditbench": {"path": str(auditbench_dir()), **git_state(auditbench_dir())},
        "annotation_sha256": annotation_file_hashes(),
        "inventory_summary": summary,
        "python": platform.python_version(),
        "packages": {name: version(name) for name in ("harbor", "wandb", "pyyaml", "huggingface_hub")},
        "model": {"id": "Qwen/Qwen3-8B", "revision": "b968826d9c46dd6066d109eabc6255188de91218"},
        "control_pool": {"id": "open-thoughts/OpenThoughts-TB-dev", "revision": "0d54f719f34dca712c8d6ef0f51df4670a2a287a"},
        "upstream_refs": {
            "harbor_train_commit": "9310ef653ae6af33d1ec11d477fdc9689461ec41",
            "skyrl_main_commit_at_review": "7daa466644ef135ea6f5305e7cf0ed261fc3e020",
            "harbor_main_commit_at_review": "3e30cca047a4d0dc1fb209bf5a74ff761b794b90",
        },
    }
    _dump(versions, VERSIONS)
    print(json.dumps(summary, indent=1))


def cmd_provenance(args) -> None:
    from .ground_truth import all_annotations
    from .inventory import load_inventory
    from .provenance import build_edges, components, group_table, write_edges

    records = load_inventory(INVENTORY)
    edges = build_edges(records, all_annotations())
    write_edges(edges, EDGES)
    mapping = components(records, edges, include_weak=args.include_weak)
    groups = group_table(records, mapping)
    _dump({"include_weak_edges": args.include_weak, "groups": groups}, GROUPS)
    rules = Counter((e.rule, e.strength) for e in edges)
    print(f"{len(edges)} edges, {len(groups)} groups")
    for (rule, strength), n in sorted(rules.items()):
        print(f"  {n:4d} {strength:6s} {rule}")


def cmd_split(args) -> None:
    from .inventory import load_inventory
    from .splits import allocate_with_ladder, split_counts, write_split_files

    records = {r.rel_path: r for r in load_inventory(INVENTORY)}
    groups = _load_json(GROUPS)["groups"]
    ladder = [tuple(map(float, s.split("/"))) for s in args.ladder]
    alloc, attempts = allocate_with_ladder(groups, ladder, args.seed, min_dev_groups=args.min_dev_groups,
                                          min_train_positive=args.min_train_positive)
    write_split_files(groups, records, alloc.assignment, SPLITS_DIR)
    counts = split_counts(groups, alloc.assignment)
    meta = {"seed": args.seed, "ladder": args.ladder, "chosen_fractions": alloc.fractions, "feasible": alloc.feasible,
            "violations": alloc.violations, "attempts": attempts, "counts": counts,
            "constraints": {"min_dev_groups_per_task_and_label": args.min_dev_groups, "min_train_positive_groups_per_task": args.min_train_positive}}
    _dump(meta, SPLITS_DIR / "allocation.json")
    print(json.dumps(meta, indent=1))
    if not alloc.feasible:
        print("WARNING: no feasible allocation in ladder; see violations", file=sys.stderr)


def _split_of_group() -> dict[str, str]:
    out = {}
    for s in ("train", "dev", "test"):
        for g in _load_json(SPLITS_DIR / f"{s}.json")["groups"]:
            out[g["group_id"]] = s
    return out


def cmd_labels(args) -> None:
    from .inventory import load_inventory
    from .labels import build_targets, summarize_targets, write_targets

    records = load_inventory(INVENTORY)
    group_of = {p: g["group_id"] for g in _load_json(GROUPS)["groups"] for p in g["files"]}
    split_of = _split_of_group()
    targets = build_targets(records)
    by_split: dict[str, list] = {"train": [], "dev": [], "test": []}
    unplaced = []
    for t in targets:
        files = [r for r in records if r.scenario_key == t.scenario_key]
        if not files:
            unplaced.append(t)
            continue
        by_split[split_of[group_of[files[0].rel_path]]].append(t)
    for s, ts in by_split.items():
        write_targets(ts, LABELS_DIR / f"{s}.jsonl")
    write_targets(unplaced, LABELS_DIR / "unplaced.jsonl")
    summary = {s: summarize_targets(ts) for s, ts in by_split.items() if s != "test"}
    summary["test"] = {"n_targets": len(by_split["test"]), "note": SEALED_TEST_NOTE,
                       "by_status": dict(Counter(t.status for t in by_split["test"]))}
    summary["unplaced"] = [{"target_id": t.target_id, "reason": t.reason} for t in unplaced]
    _dump(summary, LABELS_DIR / "summary.json")
    print(json.dumps(summary, indent=1))


def cmd_units(args) -> None:
    from .inventory import load_inventory
    from .labels import load_targets
    from .windows import build_units, summarize_units, write_units

    records = load_inventory(INVENTORY)
    group_of = {p: g["group_id"] for g in _load_json(GROUPS)["groups"] for p in g["files"]}
    split_of = _split_of_group()
    targets = [t for s in ("train", "dev", "test") for t in load_targets(LABELS_DIR / f"{s}.jsonl")]
    units = build_units(records, targets, group_of, split_of)
    for s in ("train", "dev", "test"):
        write_units([u for u in units if u.split == s], UNITS_DIR / f"{s}.jsonl")
    summary = summarize_units([u for u in units if u.split != "test"])
    summary["test"] = {"n_units": sum(u.split == "test" for u in units), "note": SEALED_TEST_NOTE}
    _dump(summary, UNITS_DIR / "summary.json")
    print(json.dumps(summary, indent=1))


def _guard_test(args, splits: list[str]) -> None:
    import os
    if "test" in splits and not (args.allow_test and os.environ.get("AUDITBENCH_ALLOW_TEST") == "1"):
        sys.exit(SEALED_TEST_NOTE)


def cmd_build(args) -> None:
    from .labels import load_targets
    from .tasks import build_task, slice_sha256
    from .windows import load_units

    _guard_test(args, args.splits)
    out_root = Path(args.out) if args.out else TASKS_DIR
    index = []
    for s in args.splits:
        targets = {t.target_id: t for t in load_targets(LABELS_DIR / f"{s}.jsonl")}
        units = load_units(UNITS_DIR / f"{s}.jsonl")
        built = 0
        for u in units:
            if u.label == "quarantined":
                continue
            build_task(u, targets, out_root / s)
            index.append({"task_id": u.task_id, "split": s, "task": u.task, "label": u.label, "dataset": u.dataset,
                          "representation": u.representation, "group_id": u.group_id, "slice_sha256": slice_sha256(u)})
            built += 1
        print(f"{s}: built {built} tasks (skipped {sum(u.label == 'quarantined' for u in units)} quarantined)")
    (out_root / "index.jsonl").write_text("".join(json.dumps(i) + "\n" for i in index))


def cmd_check(args) -> None:
    from .checks import run_all_checks
    from .labels import load_targets
    from .windows import load_units

    _guard_test(args, args.splits)
    out_root = Path(args.out) if args.out else TASKS_DIR
    index = {i["task_id"]: i for i in map(json.loads, (out_root / "index.jsonl").read_text().splitlines())}
    report = {}
    for s in args.splits:
        targets = {t.target_id: t for t in load_targets(LABELS_DIR / f"{s}.jsonl")}
        units = [u for u in load_units(UNITS_DIR / f"{s}.jsonl") if u.label != "quarantined"]
        report[s] = run_all_checks(units, targets, out_root / s, {k: v["slice_sha256"] for k, v in index.items()})
    _dump(report, REPO_ROOT / "reports" / "gate_b_checks.json")
    print(json.dumps({s: {k: (v if not isinstance(v, dict) else len(v)) for k, v in r.items()} for s, r in report.items()}, indent=1))
    bad = any(r["toml_problems"] or r["leakage_problems"] or r["oracle_failures"] for r in report.values())
    sys.exit(1 if bad else 0)


def main(argv=None) -> None:
    p = argparse.ArgumentParser(prog="auditbench-harbor", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("inventory").set_defaults(fn=cmd_inventory)
    s = sub.add_parser("provenance")
    s.add_argument("--include-weak", action="store_true")
    s.set_defaults(fn=cmd_provenance)
    s = sub.add_parser("split")
    s.add_argument("--seed", type=int, default=20261003)
    s.add_argument("--ladder", nargs="+", default=["0.5/0.1/0.4", "0.5/0.15/0.35", "0.5/0.2/0.3"])
    s.add_argument("--min-dev-groups", type=int, default=2)
    s.add_argument("--min-train-positive", type=int, default=2)
    s.set_defaults(fn=cmd_split)
    sub.add_parser("labels").set_defaults(fn=cmd_labels)
    sub.add_parser("units").set_defaults(fn=cmd_units)
    for name, fn in (("build", cmd_build), ("check", cmd_check)):
        s = sub.add_parser(name)
        s.add_argument("--splits", nargs="+", default=["train", "dev"])
        s.add_argument("--out", default=None)
        s.add_argument("--allow-test", action="store_true")
        s.set_defaults(fn=fn)
    args = p.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
