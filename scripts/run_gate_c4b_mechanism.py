"""Run Gate C.4-B Acceptance mechanism decomposition."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from fx_smc_bot.research.gate_c4b_mechanism import GateC4BPaths, run_gate_c4b


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="Repository root",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = run_gate_c4b(GateC4BPaths(root=args.root.resolve()))
    print(json.dumps(result, indent=2, sort_keys=True, default=str))


if __name__ == "__main__":
    main()
