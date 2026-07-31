"""Command-line entry point for the fail-closed Gate F0-RP-E2E orchestrator."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from fx_smc_bot.research.classical_fx_orchestrator import (
    ClassicalFXOrchestrator,
    GateStage,
    build_stage_evidence_template,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=[stage.value for stage in GateStage])
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--certify-only", action="store_true")
    parser.add_argument("--max-workers", type=int, default=1)
    parser.add_argument("--clean-room-root", type=Path)
    parser.add_argument("--output-dir", type=Path, default=Path("results/gate_f0rpe2e"))
    parser.add_argument("--evidence", type=Path)
    parser.add_argument("--synthetic-fixture", type=Path)
    return parser


def _read_json(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.certify_only and args.synthetic_fixture is None:
        raise SystemExit("--certify-only requires --synthetic-fixture")
    if args.stage is not None and args.evidence is None and not args.dry_run:
        raise SystemExit("stage promotion requires --evidence")
    if args.certify_only and args.stage is not None:
        raise SystemExit("--certify-only cannot promote a gate stage")

    orchestrator = ClassicalFXOrchestrator(
        args.output_dir,
        max_workers=args.max_workers,
        clean_room_root=args.clean_room_root,
        resume=args.resume,
    )
    if args.dry_run:
        result: dict[str, object] = {"plan": orchestrator.plan().as_dict()}
        if args.stage is not None:
            result["stage_template"] = build_stage_evidence_template(args.stage)
        if args.synthetic_fixture is not None:
            result["synthetic_certification"] = orchestrator.certify_synthetic(
                _read_json(args.synthetic_fixture), persist=False
            )
        print(json.dumps(result, allow_nan=False, indent=2, sort_keys=True))
        return 0
    if args.certify_only:
        result = orchestrator.certify_synthetic(_read_json(args.synthetic_fixture))
    elif args.stage is not None:
        result = orchestrator.advance(args.stage, _read_json(args.evidence), resume=args.resume)
    else:
        orchestrator.persist()
        result = orchestrator.plan().as_dict()
    print(json.dumps(result, allow_nan=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
