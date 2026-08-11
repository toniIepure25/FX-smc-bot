#!/usr/bin/env python3
"""Run A0R3C forensic evaluator certification."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fx_smc_bot.research.a0r3c_evaluator_certification import paths_for_a0r3c, run  # noqa: E402


def main() -> int:
    repo = Path(__file__).resolve().parents[1]
    summary = run(paths_for_a0r3c(repo))
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
