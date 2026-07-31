"""Stage-driven Gate F.0 development-data runner; dry-run by default."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from fx_smc_bot.research.classical_factor_safe_io import configured_f0_root  # noqa: E402
from fx_smc_bot.research.classical_fx_data import (  # noqa: E402
    MAXIMUM_WORKERS,
    acquire_development_market,
    certify_development_market,
    development_plan,
    static_status,
)

STAGES = (
    "status",
    "plan-development",
    "acquire-development-market",
    "certify-development-market",
)


def _iso_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected YYYY-MM-DD") from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=STAGES)
    parser.add_argument("--start", type=_iso_date, default=date(2010, 1, 1))
    parser.add_argument("--end", type=_iso_date, default=date(2016, 12, 31))
    parser.add_argument("--workers", type=int, default=MAXIMUM_WORKERS)
    parser.add_argument(
        "--root",
        type=Path,
        default=None,
        help="Exact Gate F.0 clean-room root; no directory discovery is performed.",
    )
    parser.add_argument(
        "--execute-provider",
        action="store_true",
        help="Explicitly authorize provider requests for the acquisition stage.",
    )
    parser.add_argument(
        "--execute-local",
        action="store_true",
        help="Explicitly authorize local certification reads and writes.",
    )
    return parser


def run(args: argparse.Namespace) -> dict[str, Any]:
    root = args.root or configured_f0_root(REPOSITORY_ROOT)
    if args.stage == "status":
        if args.execute_provider or args.execute_local:
            raise ValueError("status does not accept execution flags")
        return static_status()
    if args.stage == "plan-development":
        if args.execute_provider or args.execute_local:
            raise ValueError("plan-development does not accept execution flags")
        return development_plan(start=args.start, end=args.end)
    if args.stage == "acquire-development-market":
        if args.execute_local:
            raise ValueError("acquisition does not accept --execute-local")
        # development_plan performs the frozen-date rejection before any I/O.
        development_plan(start=args.start, end=args.end)
        return acquire_development_market(
            root,
            REPOSITORY_ROOT,
            workers=args.workers,
            execute_provider=args.execute_provider,
        )
    if args.stage == "certify-development-market":
        if args.execute_provider:
            raise ValueError("certification never accepts --execute-provider")
        development_plan(start=args.start, end=args.end)
        return certify_development_market(
            root,
            REPOSITORY_ROOT,
            workers=args.workers,
            execute_local=args.execute_local,
        )
    raise AssertionError("unreachable Gate F.0 stage")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = run(args)
    except (RuntimeError, ValueError) as exc:
        print(json.dumps({"status": "ERROR", "error": str(exc)}, sort_keys=True))
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
