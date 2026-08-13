"""Parallel, resumable, per-trial-durable executor for remaining V2 discovery trials.

Identical per-trial numerics to the serial runner (same frozen kernel/signals/seeds); only
scheduling is parallel. Robustness/tractability fixes over a naive pool:

* Per-trial durability: each worker appends every completed trial row to its own shard
  file immediately (flush), so a teardown loses at most the single in-flight trial, never
  a whole worker's batch.
* Memory safety: a bounded number of concurrent single-instrument workers (each loads one
  2015-2017 frame) avoids the RAM thrashing that otherwise inflates model trials 3-5x on a
  memory-starved host. BLAS threads pinned to 1.
* Shard recovery: existing shards are merged into the main checkpoint on startup, so prior
  partial progress is never recomputed.

Never opens a 2018+ file (holdout firewall enforced in every worker).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "results" / "gate_a0r5"
METRICS = OUT / "trial_metrics.jsonl"
SHARDS = OUT / "shards"
RAW = REPO / "data" / "raw" / "dukascopy-node"
MAX_CONCURRENT = int(os.environ.get("V2_DISCOVERY_WORKERS", "3"))


def _read_ids(path: Path) -> set[str]:
    if not path.exists():
        return set()
    out = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                out.add(json.loads(line)["trial_id"])
            except json.JSONDecodeError:
                pass  # ignore a partial final line from a hard kill
    return out


def _merge_shards_into_main() -> None:
    """Fold any shard rows into the main checkpoint (dedup), then clear merged shards."""

    if not SHARDS.exists():
        return
    done = _read_ids(METRICS)
    merged = 0
    with METRICS.open("a", encoding="utf-8") as fh:
        for shard in sorted(SHARDS.glob("*.jsonl")):
            for line in shard.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if row["trial_id"] not in done:
                    fh.write(json.dumps(row, sort_keys=True) + "\n")
                    done.add(row["trial_id"])
                    merged += 1
            fh.flush()
    for shard in SHARDS.glob("*.jsonl"):
        shard.unlink()
    if merged:
        print(f"merged {merged} shard rows into main checkpoint", flush=True)


def _worker(args: tuple[str, int, list[str]]) -> tuple[str, int]:
    instrument, chunk_idx, trial_ids = args
    from fx_smc_bot.research.v2 import discovery as disco
    from fx_smc_bot.research.v2.firewall import HoldoutFirewall

    SHARDS.mkdir(parents=True, exist_ok=True)
    shard = SHARDS / f"{instrument}_{chunk_idx}.jsonl"
    already = _read_ids(shard)
    todo = [t for t in trial_ids if t not in already]
    if not todo:
        return instrument, 0

    universe, _digest = disco.load_universe()
    specs = dict(universe)
    fw = HoldoutFirewall()
    frame = disco.load_instrument_frame(fw, RAW, instrument)
    assert fw.opened_2018_plus_count() == 0, "HOLDOUT VIOLATION in worker"

    done = 0
    with shard.open("a", encoding="utf-8") as fh:
        for tid in todo:
            row = disco.evaluate_trial(tid, specs[tid], frame)
            fh.write(json.dumps(row, sort_keys=True) + "\n")
            fh.flush()
            done += 1
            print(f"  worker[{instrument}#{chunk_idx}] {tid} {row['terminal_state']} "
                  f"net={row['net_bps']:.1f} {row['eval_seconds']}s", flush=True)
    return instrument, done


def main() -> None:
    import multiprocessing as mp

    from fx_smc_bot.research.v2 import discovery as disco

    OUT.mkdir(parents=True, exist_ok=True)
    _merge_shards_into_main()

    universe, digest = disco.load_universe()
    done = _read_ids(METRICS)
    remaining = [(tid, spec) for tid, spec in universe if tid not in done]
    print(f"digest={digest[:12]} remaining={len(remaining)} done={len(done)} "
          f"workers={MAX_CONCURRENT}", flush=True)
    if not remaining:
        print(f"PARALLEL EVAL COMPLETE total={len(done)}/336", flush=True)
        return

    by_inst: dict[str, list[str]] = {}
    for tid, spec in remaining:
        by_inst.setdefault(spec.instrument, []).append(tid)
    # chunks per instrument; round-robin so slow GMM/logistic trials spread evenly
    chunks = int(os.environ.get("V2_DISCOVERY_CHUNKS", "3"))
    tasks: list[tuple[str, int, list[str]]] = []
    for inst, tids in sorted(by_inst.items()):
        k = min(chunks, len(tids))
        buckets: list[list[str]] = [[] for _ in range(k)]
        for i, tid in enumerate(sorted(tids)):
            buckets[i % k].append(tid)
        tasks.extend((inst, idx, b) for idx, b in enumerate(buckets) if b)
    print(f"scheduling {len(tasks)} tasks over {MAX_CONCURRENT} concurrent workers",
          flush=True)

    ctx = mp.get_context("spawn")
    with ctx.Pool(processes=min(MAX_CONCURRENT, len(tasks))) as pool:
        for inst, n in pool.imap_unordered(_worker, tasks):
            print(f"[task done] {inst} +{n} trials", flush=True)

    _merge_shards_into_main()
    total = len(_read_ids(METRICS))
    print(f"PARALLEL EVAL COMPLETE total={total}/336", flush=True)
    if total >= 336:
        print("ALL 336 EVALUATED", flush=True)


if __name__ == "__main__":
    main()
    sys.exit(0)
