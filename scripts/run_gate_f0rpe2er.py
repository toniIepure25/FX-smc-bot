"""Run the fail-closed Gate F0-RP-E2E-R V2 orchestration state machine."""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Sequence
from pathlib import Path

from fx_smc_bot.research.classical_fx_orchestrator import (
    ClassicalFXV2Orchestrator,
    V2GateStage,
    build_v2_stage_evidence_template,
)


def _default_clean_room_root() -> Path:
    configured = os.environ.get("FX_F0RPE2ER_DATA_ROOT")
    if configured:
        return Path(configured)
    return Path.cwd().parent / "FX-smc-bot-local-data" / "f0rpe2er_v2"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=[stage.value for stage in V2GateStage])
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--certify-only", action="store_true")
    parser.add_argument("--max-workers", type=int, default=1)
    parser.add_argument("--clean-room-root", type=Path, default=_default_clean_room_root())
    parser.add_argument("--output-dir", type=Path, default=Path("results/gate_f0rpe2er"))
    parser.add_argument("--evidence", type=Path)
    return parser


def _read_json(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.stage is not None and args.evidence is None and not args.dry_run:
        raise SystemExit("stage promotion requires --evidence")
    if args.certify_only and args.stage is None:
        raise SystemExit("--certify-only requires --stage")

    orchestrator = ClassicalFXV2Orchestrator(
        args.output_dir,
        clean_room_root=args.clean_room_root,
        max_workers=args.max_workers,
        resume=args.resume,
    )
    if args.dry_run:
        result: dict[str, object] = {
            "mode": "CERTIFY_ONLY" if args.certify_only else "DRY_RUN",
            "plan": orchestrator.plan().as_dict(),
        }
        if args.stage is not None:
            result["stage_template"] = build_v2_stage_evidence_template(args.stage)
        print(json.dumps(result, allow_nan=False, indent=2, sort_keys=True))
        return 0
    if args.stage is None:
        orchestrator.persist()
        result = orchestrator.plan().as_dict()
    else:
        result = orchestrator.advance(
            args.stage,
            _read_json(args.evidence),
            resume=args.resume,
            certify_only=args.certify_only,
        )
    print(json.dumps(result, allow_nan=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
