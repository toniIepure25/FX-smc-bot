"""Dry-run and readiness runner for the frozen Gate F0-RP amendment."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from fx_smc_bot.research.classical_fx_f0rp import (  # noqa: E402
    amendment_overlay,
    development_market_plan,
    development_rate_plan,
    execution_readiness,
)

STAGES = (
    "status",
    "amendment",
    "plan-development-market",
    "plan-development-rates",
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=STAGES)
    return parser


def run(args: argparse.Namespace) -> dict[str, Any]:
    if args.stage == "status":
        return execution_readiness()
    if args.stage == "amendment":
        return amendment_overlay()
    if args.stage == "plan-development-market":
        return development_market_plan()
    if args.stage == "plan-development-rates":
        return development_rate_plan()
    raise AssertionError("unreachable Gate F0-RP stage")


def main(argv: list[str] | None = None) -> int:
    result = run(build_parser().parse_args(argv))
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
