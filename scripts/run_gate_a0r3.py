#!/usr/bin/env python3
"""Run A0R3 existing-data eligibility audit and exploratory discovery."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fx_smc_bot.research.a0r3_existing_data import Paths, run  # noqa: E402


def main() -> int:
    repo = Path(__file__).resolve().parents[1]
    paths = Paths(
        repo=repo,
        raw=repo / "data" / "raw" / "dukascopy-node",
        results=repo / "results" / "gate_a0r3",
        docs=repo / "docs" / "research" / "fx_alpha_discovery",
        trials=repo / "results" / "gate_a0r2" / "trial_materialization_v2.jsonl",
    )
    summary = run(paths)
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
