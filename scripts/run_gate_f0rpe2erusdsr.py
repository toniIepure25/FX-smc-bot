"""Run bounded, outcome-blind structural discovery for Gate F0-RP-E2E-R-USDSR."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

from fx_smc_bot.research.official_response_shape import (
    INSPECTOR_ID,
    OfficialResponseShape,
    OfficialResponseShapeInspector,
)
from fx_smc_bot.research.rate_sources.base import (
    OfficialNumericalEndpoint,
    OfficialRateRequest,
    RateAccessAuthorization,
    SourceSnapshot,
)
from fx_smc_bot.research.rate_sources.client import OfficialRateSnapshotClient
from fx_smc_bot.research.rate_sources.new_york_fed import NewYorkFedEffrAdapterV2

WINDOWS = {
    "legacy": (date(2016, 1, 4), date(2016, 1, 8), "LEGACY_PRE_FIELD_CHANGE_SCHEMA"),
    "modern": (date(2016, 3, 1), date(2016, 3, 4), "MODERN_POST_FIELD_CHANGE_SCHEMA"),
}


@dataclass(slots=True)
class ShapeInspectionFirewall:
    authorization: RateAccessAuthorization
    declaration: OfficialNumericalEndpoint
    shape: OfficialResponseShape | None = None
    firewall_id: str = field(init=False)

    def __post_init__(self) -> None:
        self.firewall_id = self.declaration.firewall_id

    def validate_request(self, request: OfficialRateRequest) -> None:
        self.authorization.authorize(request)
        self.declaration.validate_request(request)

    def validate_snapshot(self, snapshot: SourceSnapshot) -> None:
        self.shape = OfficialResponseShapeInspector(self.authorization).inspect(snapshot)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--window", required=True, choices=tuple(WINDOWS))
    parser.add_argument("--clean-room-root", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=float, default=45.0)
    parser.add_argument("--dry-run", action="store_true")
    return parser


def _authorization(
    declaration: OfficialNumericalEndpoint,
    start: date,
    end: date,
) -> RateAccessAuthorization:
    return RateAccessAuthorization(
        authorization_id=f"F0RPE2ERUSDSR_{declaration.series_id}_{start}_{end}",
        adapter_ids=frozenset({declaration.adapter_id}),
        currencies=frozenset({declaration.currency}),
        series_ids=frozenset({declaration.series_id}),
        start=start,
        end=end,
        official_hosts=frozenset({urlparse(declaration.url).hostname or ""}),
        source_allowlist_identities=frozenset({declaration.allowlist_identity}),
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    start, end, role = WINDOWS[args.window]
    adapter = NewYorkFedEffrAdapterV2()
    declaration = adapter.endpoint_declarations[0]
    authorization = _authorization(declaration, start, end)
    request = adapter.build_requests(start, end, authorization)[0]
    summary: dict[str, object] = {
        "inspector_id": INSPECTOR_ID,
        "window": args.window,
        "role": role,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "adapter_id": adapter.adapter_id,
        "series_id": adapter.series_id,
        "request_identity": request.request_identity,
        "server_side_bounds": "PASS",
        "request_count": 0 if args.dry_run else 1,
        "snapshot_count": 0,
        "status": "DRY_RUN" if args.dry_run else "PENDING",
    }
    if not args.dry_run:
        firewall = ShapeInspectionFirewall(authorization, declaration)
        snapshot = OfficialRateSnapshotClient(
            args.clean_room_root / "official-rate-snapshots",
            timeout_seconds=args.timeout_seconds,
        ).fetch(request, authorization, response_firewall=firewall)
        if firewall.shape is None:
            raise RuntimeError("Structural inspector did not produce a descriptor")
        summary.update(
            {
                "snapshot_count": 1,
                "snapshot_sha256": snapshot.source_snapshot_sha256,
                "descriptor": firewall.shape.to_record(),
                "status": "PASS",
            }
        )
    print(json.dumps(summary, allow_nan=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
