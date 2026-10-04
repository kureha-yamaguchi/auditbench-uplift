#!/usr/bin/env python
"""Differential test of grader.compat against the upstream AuditBench metric code (PLAN.md §4).

For every shipped v2 LLM output in the AuditBench checkout, this script
  1. parses the file with the *upstream* parser and scores it with the *upstream* ErrorInvestigation
     code (run from inside `inference/`, exactly as the paper pipeline does), and
  2. converts the same upstream-parsed tuples into grader.Finding objects and scores them with
     grader.compat,
then compares TP/FP/FN per round. Mismatches are reported, not hidden. Upstream's parser is
whitespace/line-order sensitive, so only its own parse is used here; the comparison isolates the
*counting conventions*, which is what the compatibility scorer re-implements.
"""
from __future__ import annotations

import io
import json
import os
import sys
from contextlib import redirect_stdout
from pathlib import Path

from auditbench_harbor.paths import REPO_ROOT, auditbench_dir
from grader.compat import CompatScenario, score_attempt
from grader.schema import Finding

ENTITY_FIELD = {"lm": "external host", "persistence": "mechanism_name", "exfiltration": "exfiltrated data"}
PRECISION = {("labgen", "lm"): "second", ("labgen", "persistence"): "minute", ("labgen", "exfiltration"): "minute"}


def upstream_modules():
    inference = auditbench_dir() / "inference"
    os.chdir(inference)
    sys.path.insert(0, str(inference))
    from metrics_comp.factory import ModuleFactory  # noqa: E402
    return ModuleFactory("v2")


def tuples_to_findings(task: str, llmresponse: dict, dataset: str) -> dict[int, dict[str, list[Finding]]]:
    """upstream {chunk: {round: [tuple]}} -> {round: {chunk: [Finding]}} (tuple layouts per parser)."""
    out: dict[int, dict[str, list[Finding]]] = {}
    for chunk, rounds in llmresponse.items():
        for rnd, tups in rounds.items():
            fs = []
            for i, t in enumerate(tups):
                if task == "classification":
                    fs.append(Finding(i, t[-1].upper(), [], None, None))
                    continue
                ts, ent = t[1], t[2]
                if ts is None or ent is None or (ts, ent) == ("", ""):
                    continue
                # upstream already converted the timestamp to ground-truth form; feed it through as ISO
                fs.append(Finding(i, str(t[-1]).upper(), [], ts, str(ent)))
            out.setdefault(rnd, {})[str(chunk)] = fs
    return out


def main() -> None:
    modules = upstream_modules()
    results = []
    for dataset, folder in (("labgen", "labgen_expt_dataset"), ("optc", "optc_expt_dataset")):
        for out_file in sorted(Path(folder).glob("task_*/*/output/*/*_v2_*.txt")):
            task = out_file.parts[1].removeprefix("task_")
            gt_key = out_file.name.split("_")[5 if dataset == "labgen" else 6].split(".")[0]
            parser_cls = {"lm": modules.ParserLateralMovement, "persistence": modules.ParserPersistence,
                          "exfiltration": modules.ParserExfiltration, "classification": modules.ParserClassification}[task]
            parser = parser_cls(dataset, task)
            with redirect_stdout(io.StringIO()):
                llmresponse, _ = getattr(parser, f"parse_{'lateralmovement' if task == 'lm' else task}_llmoutput")(str(out_file))
            input_name = "_".join(out_file.name.split("_")[3:6 if dataset == "labgen" else 7])
            log_lines = sum(1 for _ in open(out_file.parents[2] / "input" / input_name, errors="replace"))
            ei = modules.ErrorInvestigation(dataset, task)
            upstream = {}
            with redirect_stdout(io.StringIO()):
                if task == "classification":
                    benign_d, mal_d, n_chunks = ei.compute_chunkdecision(llmresponse, False)
                    for rnd in mal_d:
                        upstream[rnd] = {"high_chunks": mal_d[rnd], "chunks": n_chunks}
                    annotations = []
                else:
                    gt_set = parser.read_task_groudtruth(gt_key)
                    fp_d, tp_d, fn_d, _ = ei.compute_confusionmatrix(llmresponse, gt_set, gt_key, False)
                    fp_r = ei.get_fpperround_from_dict(fp_d)
                    tp_r = ei.get_tpperround_from_dict(tp_d) if "benign" not in gt_key else []
                    for idx, rnd in enumerate(sorted(fp_d)):
                        upstream[rnd] = {"fp": fp_r[idx], "tp": tp_r[idx] if idx < len(tp_r) else 0, "fn": fn_d.get(rnd, 0)}
                    annotations = [{"timestamp": sorted({t for t, _ in gt_set}), ENTITY_FIELD[task]: sorted({e for _, e in gt_set})}]
                    # NOTE: upstream builds the product per record and unions; reconstructing from the set is
                    # exact for single-record scenarios and a superset otherwise (reported below).
            ours_in = tuples_to_findings(task, llmresponse, dataset)
            sc = CompatScenario("lab" if dataset == "labgen" else "optc", task, gt_key, "benign" if "benign" in gt_key else "attack",
                                log_lines, PRECISION.get((dataset, task), "second"), annotations, ENTITY_FIELD.get(task, ""))
            for rnd, chunks in ours_in.items():
                c = score_attempt(sc, chunks)
                ours = {"high_chunks": c.fp if sc.label == "benign" else c.tp, "chunks": c.chunks} if task == "classification" \
                    else {"fp": c.fp, "tp": c.tp, "fn": c.fn}
                up = upstream.get(rnd, {})
                results.append({"file": out_file.name, "task": task, "dataset": dataset, "round": rnd,
                                "upstream": up, "ours": ours, "match": all(up.get(k) == v for k, v in ours.items() if k in up)})
    report = {"n_compared": len(results), "n_mismatch": sum(not r["match"] for r in results), "results": results,
              "coverage_note": "shipped outputs cover Lab edge only, one chunk each; raw/OpTC and multi-round cases are covered by tests/test_grader_compat.py synthetic fixtures"}
    out = REPO_ROOT / "reports" / "compat_differential.json"
    out.write_text(json.dumps(report, indent=1, default=str) + "\n")
    for r in results:
        print(("OK  " if r["match"] else "DIFF"), r["task"], r["file"][:60], "upstream", r["upstream"], "ours", r["ours"])
    print(f"{report['n_compared']} compared, {report['n_mismatch']} mismatches -> {out}")
    sys.exit(1 if report["n_mismatch"] else 0)


if __name__ == "__main__":
    main()
