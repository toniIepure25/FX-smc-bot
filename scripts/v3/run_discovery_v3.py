"""Run the frozen V3.1 alpha discovery (992 Universe-A + 52 Universe-B candidates).

Pre-run assertions (all must hold before any outcome is computed):
  * HEAD == the V3.1 amendment commit and the working tree is clean;
  * the V3.1 freeze hash and global data digest match the certified artifacts;
  * the frozen universe counts (992 / 52 / 1044) reproduce from the compiler;
  * the acquisition state counts (32117/406/28/1) and monthly certification
    counts (2440/54/2) match the certified gate.

The run is checkpointed (freeze_hash + data_digest + registry_hash keyed) and
resumable. Artifacts:
  * results/gate_v3f/v3_1_discovery_decision.json  (lightweight, committed)
  * D:\\ComputaCenter\\v3_processing\\discovery_results\\  (operational: full
    candidate rows, firewall counters, reproducibility manifest)

The sealed 2018+ holdout is structurally inaccessible: every canonical read goes
through DiscoveryFirewall, which blocks 2018+ years before I/O and counts every
file/byte touched.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from fx_smc_bot.research.v3 import discovery_engine as de  # noqa: E402
from fx_smc_bot.research.v3.discovery_data import DiscoveryFirewall  # noqa: E402
from fx_smc_bot.research.v3.universes import assert_invariants, universe_counts  # noqa: E402

OUT = REPO / "results" / "gate_v3f"
CANON = Path(r"D:\ComputaCenter\v3_processing\canonical")
CACHE = Path(r"D:\ComputaCenter\v3_processing\discovery_cache")
CKPT = Path(r"D:\ComputaCenter\v3_processing\discovery_results")
STATE = Path(r"D:\ComputaCenter\v3_processing\state\acquisition_state.json")

# The discovery engine is committed ON TOP of the V3.1 amendment commit; the run must be a
# clean descendant of it (the exact HEAD is recorded in the reproducibility manifest).
AMENDMENT_HEAD = "79c335ad9b4467a8bea741db9bdc42af257a0039"
EXPECTED_FREEZE_HASH = "5587babc9978343fb09469963822003b552b6c44e92dee373599160bdad356fd"
EXPECTED_DATA_DIGEST = "15a5c1af697c85dfaa454812aa8061b2a4d97fafa956196210bc3b38415d11c0"
EXPECTED_STATE_COUNTS = {"CERTIFIED_NATIVE": 32117, "CERTIFIED_TICK_FALLBACK": 406,
                         "TERMINAL_DATA_ABSENT": 28, "UNRESOLVED_DATA_GAP": 1}
EXPECTED_MONTHLY_COUNTS = {"CERTIFIED_COMPLETE": 2440,
                           "CERTIFIED_WITH_PROSPECTIVE_ABSENCE": 54,
                           "USABLE_WITH_UNRESOLVED_DATA_GAP": 2}


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=REPO, capture_output=True,
                          text=True, check=True).stdout.strip()


def _is_ancestor(base: str, head: str) -> bool:
    r = subprocess.run(["git", "merge-base", "--is-ancestor", base, head],
                       cwd=REPO, capture_output=True)
    return r.returncode == 0


def pre_run_assertions() -> dict[str, Any]:
    head = _git("rev-parse", "HEAD")
    branch = _git("rev-parse", "--abbrev-ref", "HEAD")
    subject = _git("log", "-1", "--format=%s")
    assert _is_ancestor(AMENDMENT_HEAD, head), \
        f"V3_1_PRE_RUN: HEAD {head} is not a descendant of amendment {AMENDMENT_HEAD}"
    dirty = _git("status", "--porcelain")
    assert dirty == "", f"V3_1_PRE_RUN: working tree not clean:\n{dirty}"

    freeze = json.loads((OUT / "v3_1_freeze_manifest.json").read_text())
    assert freeze["freeze_hash"] == EXPECTED_FREEZE_HASH, "V3_1_PRE_RUN: freeze hash mismatch"
    gate = json.loads((OUT / "v3_1_data_certification_gate.json").read_text())
    digest = gate["monthly_certification"]["global_data_freeze_digest"]["global_digest"]
    assert digest == EXPECTED_DATA_DIGEST, "V3_1_PRE_RUN: data digest mismatch"

    counts = universe_counts()
    assert_invariants(counts)
    assert counts["A_executable_alpha"] == 992 and counts["B_price_alpha_only"] == 52 \
        and counts["C_total_v3_registry"] == 1044, \
        f"V3_1_PRE_RUN: universe counts {counts}"

    state = json.loads(STATE.read_text())
    from collections import Counter
    state_counts = dict(Counter(v["status"] for v in state.values()))
    assert state_counts == EXPECTED_STATE_COUNTS, \
        f"V3_1_PRE_RUN: state counts {state_counts} != {EXPECTED_STATE_COUNTS}"
    unresolved = [k for k, v in state.items() if v["status"] == "UNRESOLVED_DATA_GAP"]
    assert unresolved == ["USDJPY:2010-01-01"], f"V3_1_PRE_RUN: unresolved {unresolved}"

    monthly = gate["monthly_certification"]
    mcounts = dict(monthly["status_counts"])
    assert mcounts == EXPECTED_MONTHLY_COUNTS, \
        f"V3_1_PRE_RUN: monthly counts {mcounts} != {EXPECTED_MONTHLY_COUNTS}"

    return {"head": head, "branch": branch, "commit_subject": subject,
            "amendment_head": AMENDMENT_HEAD, "freeze_hash": freeze["freeze_hash"],
            "global_data_digest": digest, "universe_counts": counts,
            "state_counts": state_counts, "monthly_counts": mcounts}


def _compact_row(row: dict[str, Any]) -> dict[str, Any]:
    out = {k: v for k, v in row.items()
           if k not in ("daily_dates_primary", "daily_net_bps_primary", "folds")}
    return out


def main() -> int:
    os.environ.setdefault("OMP_NUM_THREADS", "1")
    os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
    os.environ.setdefault("MKL_NUM_THREADS", "1")
    print("== V3.1 DISCOVERY RUN ==", flush=True)
    pre = pre_run_assertions()
    print(f"pre-run assertions OK: {json.dumps(pre, indent=1)}", flush=True)

    CKPT.mkdir(parents=True, exist_ok=True)
    fw = DiscoveryFirewall()
    result = de.run_discovery(
        canonical=CANON,
        cache_dir=CACHE,
        ckpt_root=CKPT,
        freeze_hash=EXPECTED_FREEZE_HASH,
        data_digest=EXPECTED_DATA_DIGEST,
        fw=fw,
    )

    rows = result.pop("candidate_rows")
    with (CKPT / "candidate_rows.jsonl").open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, sort_keys=True) + "\n")
    (CKPT / "firewall.json").write_text(json.dumps(fw.as_dict(), indent=1))
    (CKPT / "pre_run_assertions.json").write_text(json.dumps(pre, indent=1))
    (CKPT / "reproducibility_manifest.json").write_text(json.dumps({
        "head": pre["head"], "branch": pre["branch"],
        "commit_subject": pre["commit_subject"],
        "amendment_head": pre["amendment_head"],
        "freeze_hash": pre["freeze_hash"],
        "global_data_digest": pre["global_data_digest"],
        "candidate_registry_hash": result["candidate_registry_hash"],
        "engine": "fx_smc_bot.research.v3.discovery_engine",
        "built_at": datetime.now(timezone.utc).isoformat(),
    }, indent=1))

    decision = {k: v for k, v in result.items()}
    decision["candidate_rows_compact"] = [_compact_row(r) for r in rows]
    decision["pre_run_assertions"] = pre
    decision["built_at"] = datetime.now(timezone.utc).isoformat()
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "v3_1_discovery_decision.json").write_text(json.dumps(decision, indent=1))

    print("\n== TERMINAL REPORT ==", flush=True)
    print(f"verdict: {result['terminal_verdict']}", flush=True)
    print(f"next_gate: {result['next_gate']}", flush=True)
    print(f"universe_A: {json.dumps(result['universe_A'])}", flush=True)
    print(f"universe_B: {json.dumps(result['universe_B'])}", flush=True)
    st = result["statistics"]
    print(f"WRC p={st['white_reality_check_p']} SPA p={st['hansen_spa_p']} "
          f"PBO={st['pbo'].get('pbo')}", flush=True)
    print(f"RW significant={st['romano_wolf_significant']} "
          f"Holm significant={st['holm_significant']} "
          f"BH significant={st['bh_fdr_significant']} "
          f"hierarchical significant={st['hierarchical_significant_count']}", flush=True)
    print(f"survivors: {len(result['survivors'])}", flush=True)
    for s in result["survivors"]:
        print(f"  {s['candidate_id']} {s['family_id']} {s['scope']} "
              f"net={s['net_bps']} sharpe={s['daily_sharpe']} dsr={s['dsr']}", flush=True)
    print(f"firewall: {json.dumps(fw.as_dict())}", flush=True)
    print(f"wall_seconds: {result['wall_seconds']}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
