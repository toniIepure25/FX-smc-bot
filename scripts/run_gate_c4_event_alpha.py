"""Run Gate C.4 USDJPY event-alpha preregistration or analysis."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from fx_smc_bot.research.gate_c4_event_alpha import (
    GateC4Paths,
    run_analysis,
    run_preregistration,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["preregister", "analyze"], required=True)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="Repository root",
    )
    parser.add_argument(
        "--starting-sha",
        default=None,
        help="Expected starting SHA for preregistration repository_state.json",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    paths = GateC4Paths(root=args.root.resolve())
    if args.mode == "preregister":
        result = run_preregistration(paths, args.starting_sha)
    else:
        result = run_analysis(paths)
    print(json.dumps(result, indent=2, sort_keys=True, default=str))


if __name__ == "__main__":
    main()
