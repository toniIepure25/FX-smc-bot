"""Run Gate C.5-A amendment or development replay phases."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from fx_smc_bot.research.gate_c5a_amendment import (
    GateC5APaths,
    initialize_amendment,
    run_development_replay,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["amend", "development-replay"], required=True)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="Repository root",
    )
    parser.add_argument(
        "--expected-sha",
        default="771ac92773ba9bf5c67afe71b5d3788c73b08304",
        help="Expected starting SHA for the amendment phase",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    paths = GateC5APaths(root=args.root.resolve())
    if args.mode == "amend":
        result = initialize_amendment(paths, args.expected_sha)
    else:
        result = run_development_replay(paths)
    print(json.dumps(result, indent=2, sort_keys=True, default=str))


if __name__ == "__main__":
    main()
