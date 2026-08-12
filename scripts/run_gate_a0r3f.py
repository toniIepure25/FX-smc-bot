#!/usr/bin/env python3
"""Run A0R3F remaining semantic closure and stop-before-2018 gate."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fx_smc_bot.research.a0r3f_stop_before_2018 import paths_for_a0r3f, run  # noqa: E402


def main() -> int:
    repo = Path(__file__).resolve().parents[1]
    summary = run(paths_for_a0r3f(repo))
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
