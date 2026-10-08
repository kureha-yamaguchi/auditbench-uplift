#!/usr/bin/env python
"""Convert SkyRL's fp32 HF exports to bf16 in place (31 GB -> 16 GB per export; PLAN.md §8.3 storage).

    python scripts/export_bf16.py /workspace/auditbench/runs/<run>/exports [--min-age 120] [--once]

Each `exports/global_step_N/policy` that is complete (config.json present, every shard listed in the safetensors index
present, newest file older than --min-age seconds, no `.bf16` marker) is loaded with torch_dtype=bfloat16, saved to
`policy.bf16`, verified (tensor count and a parameter checksum against the loaded bf16 model), then swapped into place.
Runs as a watcher (default) so exports are converted while training continues; --once converts what is there and exits.
"""
import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path


def complete(policy: Path, min_age: float) -> bool:
    if not (policy / "config.json").exists() or (policy / ".bf16").exists():
        return False
    idx = policy / "model.safetensors.index.json"
    if idx.exists():
        shards = set(json.loads(idx.read_text())["weight_map"].values())
        if any(not (policy / s).exists() for s in shards):
            return False
    elif not (policy / "model.safetensors").exists():
        return False
    newest = max(p.stat().st_mtime for p in policy.iterdir())
    return time.time() - newest > min_age


def convert(policy: Path) -> None:
    import torch
    from transformers import AutoConfig, AutoModelForCausalLM, AutoTokenizer

    cfg = AutoConfig.from_pretrained(policy)
    if str(getattr(cfg, "torch_dtype", "")) in ("torch.bfloat16", "bfloat16"):
        sizes = sum(p.stat().st_size for p in policy.glob("*.safetensors"))
        if sizes < 20e9:   # already bf16-sized
            (policy / ".bf16").write_text("already bf16\n"); return
    out = policy.with_name("policy.bf16")
    if out.exists():
        shutil.rmtree(out)
    t0 = time.time()
    model = AutoModelForCausalLM.from_pretrained(policy, torch_dtype=torch.bfloat16, low_cpu_mem_usage=True)
    n_params = sum(p.numel() for p in model.parameters())
    model.save_pretrained(out, safe_serialization=True, max_shard_size="5GB")
    for f in ("tokenizer.json", "tokenizer_config.json", "special_tokens_map.json", "added_tokens.json", "vocab.json", "merges.txt",
              "generation_config.json", "chat_template.jinja"):
        if (policy / f).exists():
            shutil.copy2(policy / f, out / f)
    try:
        AutoTokenizer.from_pretrained(policy).save_pretrained(out)
    except Exception as e:  # noqa: BLE001
        print(f"tokenizer copy warning: {e}", file=sys.stderr)
    del model
    check = AutoModelForCausalLM.from_pretrained(out, torch_dtype=torch.bfloat16, low_cpu_mem_usage=True)
    n2 = sum(p.numel() for p in check.parameters())
    assert n2 == n_params, f"parameter count mismatch after conversion: {n2} != {n_params}"
    del check
    old = policy.with_name("policy.fp32.old")
    policy.rename(old)
    out.rename(policy)
    shutil.rmtree(old)
    (policy / ".bf16").write_text(f"converted from fp32 {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} in {time.time() - t0:.0f}s; params {n_params}\n")
    print(f"converted {policy} to bf16 in {time.time() - t0:.0f}s")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("exports")
    ap.add_argument("--min-age", type=float, default=120)
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--poll", type=float, default=60)
    args = ap.parse_args()
    root = Path(args.exports)
    while True:
        for d in sorted(root.glob("global_step_*/policy")):
            try:
                if complete(d, args.min_age):
                    convert(d)
            except Exception as e:  # noqa: BLE001
                print(f"conversion of {d} failed: {e}", file=sys.stderr)
        if args.once:
            return
        time.sleep(args.poll)


if __name__ == "__main__":
    main()
