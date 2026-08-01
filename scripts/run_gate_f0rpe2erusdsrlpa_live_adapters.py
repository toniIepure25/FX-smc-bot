"""Run Phase 13 bounded live-adapter certification for Gate F0RPE2ERUSDSRLPA.

The runner is deliberately fail-fast and value-blind.  It validates frozen V2
endpoint declarations, then lets the historical response firewall inspect the
complete official response before any snapshot can be persisted or parsed.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from dataclasses import asdict
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

import httpx

from fx_smc_bot.research.historical_response_firewall import (
    HistoricalResponseFirewall,
    HistoricalResponseFirewallError,
)
from fx_smc_bot.research.rate_sources.bank_of_canada import BankOfCanadaAdapterV2
from fx_smc_bot.research.rate_sources.bank_of_england import BankOfEnglandSoniaAdapterV2
from fx_smc_bot.research.rate_sources.bank_of_japan import BankOfJapanCallRateAdapterV2
from fx_smc_bot.research.rate_sources.base import (
    OfficialRateAdapter,
    RateAccessAuthorization,
    RateSourceError,
)
from fx_smc_bot.research.rate_sources.client import OfficialRateSnapshotClient
from fx_smc_bot.research.rate_sources.ecb import EcbEoniaEstrAdapterV2
from fx_smc_bot.research.rate_sources.rba import RbaCashRateAdapterV2
from fx_smc_bot.research.rate_sources.saron import Saron18AdapterV2

GATE_ID = "F0RPE2ERUSDSRLPA_LEGACY_PUBLICATION_AVAILABILITY_V1"
ARTIFACT_ID = "F0RPE2ERUSDSRLPA_LIVE_ADAPTER_CERTIFICATION_V1"
MATRIX_ID = "F0RPE2ERUSDSRLPA_LIVE_ADAPTER_MATRIX_V1"
EONIA_AUDIT_ID = "F0RPE2ERUSDSRLPA_EONIA_ESTR_TRANSITION_AUDIT_V1"
ALLOWLIST_ID = "F0RPE2ER_OFFICIAL_SOURCE_ALLOWLIST_V1"
USD_V3_CERTIFICATION_SHA = "f92e5a315094d61d7118fdcf07fbae403a8b414f"


ADAPTER_ORDER: tuple[tuple[str, type[OfficialRateAdapter], date, date], ...] = (
    ("EUR", EcbEoniaEstrAdapterV2, date(2019, 9, 27), date(2019, 10, 4)),
    ("GBP", BankOfEnglandSoniaAdapterV2, date(2018, 4, 23), date(2018, 4, 27)),
    ("AUD", RbaCashRateAdapterV2, date(2016, 5, 2), date(2016, 5, 6)),
    ("JPY", BankOfJapanCallRateAdapterV2, date(2016, 1, 4), date(2016, 1, 8)),
    ("CAD", BankOfCanadaAdapterV2, date(2016, 1, 18), date(2016, 1, 22)),
    ("CHF", Saron18AdapterV2, date(2016, 1, 4), date(2016, 1, 8)),
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--clean-room-root", type=Path, required=True)
    parser.add_argument(
        "--results-dir",
        type=Path,
        default=Path("results/gate_f0rpe2erusdsrlpa"),
    )
    parser.add_argument("--timeout-seconds", type=float, default=45.0)
    parser.add_argument("--dry-run", action="store_true")
    return parser


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _must_be_outside_git(path: Path, label: str) -> Path:
    resolved = path.resolve()
    repo = _repo_root().resolve()
    if resolved == repo or repo in resolved.parents:
        raise RuntimeError(f"{label}_MUST_BE_OUTSIDE_GIT")
    return resolved


def _authorization(
    adapter: OfficialRateAdapter,
    start: date,
    end: date,
) -> RateAccessAuthorization:
    declarations = adapter.endpoint_declarations  # type: ignore[attr-defined]
    return RateAccessAuthorization(
        authorization_id=f"F0RPE2ERUSDSRLPA_{adapter.adapter_id}_{start}_{end}",
        adapter_ids=frozenset({adapter.adapter_id}),
        currencies=frozenset({adapter.currency}),
        series_ids=frozenset(item.series_id for item in declarations),
        start=start,
        end=end,
        official_hosts=frozenset(urlparse(item.url).hostname or "" for item in declarations),
        source_allowlist_identities=frozenset({ALLOWLIST_ID}),
    )


def _pending(currency: str, adapter_id: str) -> dict[str, object]:
    return {
        "adapter_id": adapter_id,
        "status": "NOT_RUN_AFTER_FAIL_FAST",
        "official_publisher": "NOT_RUN",
        "exact_endpoint": "NOT_RUN",
        "server_side_date_range": "NOT_RUN",
        "series_identity": "NOT_RUN",
        "response_schema": "NOT_RUN",
        "response_firewall": "NOT_RUN",
        "parser": "NOT_RUN",
        "publication_rule": "NOT_RUN",
        "as_of_availability": "NOT_RUN",
        "currency": currency,
    }


def _preflighted(currency: str, adapter: OfficialRateAdapter) -> dict[str, object]:
    return {
        "adapter_id": adapter.adapter_id,
        "currency": currency,
        "official_publisher": "PASS",
        "exact_endpoint": "PASS",
        "server_side_date_range": "PASS",
        "series_identity": "PASS",
        "response_schema": "PENDING",
        "response_firewall": "PENDING",
        "parser": "NOT_RUN",
        "publication_rule": "NOT_RUN",
        "as_of_availability": "NOT_RUN",
        "status": "PENDING",
    }


def _failure_code(exc: BaseException) -> tuple[str, dict[str, object] | None, str]:
    if isinstance(exc, HistoricalResponseFirewallError):
        return exc.violation.code, asdict(exc.violation), "BLOCKED_BY_OFFICIAL_RATE_ADAPTER"
    if isinstance(exc, RateSourceError):
        return str(exc), None, "BLOCKED_BY_RATE_SOURCE_ACCESS"
    if isinstance(exc, httpx.HTTPError):
        return "RATE_SOURCE_ACCESS_FAILURE", None, "BLOCKED_BY_RATE_SOURCE_ACCESS"
    return type(exc).__name__, None, "BLOCKED_BY_OFFICIAL_RATE_ADAPTER"


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, allow_nan=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_artifacts(
    results_dir: Path,
    matrix: dict[str, object],
    certification: dict[str, object],
    eonia_audit: dict[str, object],
) -> None:
    _write_json(results_dir / "live_adapter_matrix.json", matrix)
    _write_json(results_dir / "live_adapter_certification.json", certification)
    _write_json(results_dir / "eonia_estr_transition_audit.json", eonia_audit)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    clean_room_root = _must_be_outside_git(args.clean_room_root, "CLEAN_ROOM_ROOT")
    results_dir = args.results_dir
    matrix_adapters: dict[str, dict[str, object]] = {}
    certification_adapters: dict[str, dict[str, object]] = {}
    request_windows: list[dict[str, object]] = []
    request_count = 0
    persisted_count = 0
    failure: dict[str, object] | None = None

    for currency, adapter_type, start, end in ADAPTER_ORDER:
        adapter = adapter_type()
        matrix_adapters[currency] = _preflighted(currency, adapter)
        authorization = _authorization(adapter, start, end)
        requests = tuple(adapter.build_requests(start, end, authorization))
        request_windows.extend(
            {
                "currency": currency,
                "adapter_id": adapter.adapter_id,
                "series_id": request.series_id,
                "start": request.start.isoformat(),
                "end": request.end.isoformat(),
                "request_identity": request.request_identity,
                "endpoint_declaration_sha256": request.endpoint_declaration.declaration_sha256
                if request.endpoint_declaration is not None
                else None,
            }
            for request in requests
        )
        for request in requests:
            declaration = request.endpoint_declaration
            if declaration is None:
                raise RuntimeError("ENDPOINT_DECLARATION_REQUIRED")
            if args.dry_run:
                continue
            request_count += 1
            firewall = HistoricalResponseFirewall.from_endpoint_declaration(declaration)
            try:
                OfficialRateSnapshotClient(
                    clean_room_root / "official-rate-snapshots",
                    timeout_seconds=args.timeout_seconds,
                ).fetch(request, authorization, response_firewall=firewall)
            except Exception as exc:  # noqa: BLE001 - sanitized below for gate artifact.
                code, violation, decision = _failure_code(exc)
                matrix_adapters[currency].update(
                    {
                        "response_schema": "FAIL",
                        "response_firewall": "FAIL_CLOSED",
                        "status": "FAIL",
                        "failure_code": code,
                    }
                )
                failure = {
                    "currency": currency,
                    "adapter_id": adapter.adapter_id,
                    "series_id": request.series_id,
                    "failure_code": code,
                    "failure_stage": (
                        violation["stage"] if violation is not None else "RATE_SOURCE_ACCESS"
                    ),
                    "failure_disposition": (
                        violation["disposition"]
                        if violation is not None
                        else "NO_SOURCE_SNAPSHOT_PERSISTED"
                    ),
                    "blocking_decision": decision,
                }
                break
            persisted_count += 1
            matrix_adapters[currency].update(
                {
                    "response_schema": "PASS",
                    "response_firewall": "PASS",
                    "parser": "NOT_RUN_VALUE_BLIND_PHASE13_SCHEMA_ONLY",
                    "publication_rule": "NOT_RUN_VALUE_BLIND_PHASE13_SCHEMA_ONLY",
                    "as_of_availability": "NOT_RUN_VALUE_BLIND_PHASE13_SCHEMA_ONLY",
                    "status": "PASS",
                }
            )
        certification_adapters[currency] = dict(matrix_adapters[currency])
        if failure is not None:
            break

    for currency, adapter_type, _start, _end in ADAPTER_ORDER:
        if currency not in matrix_adapters:
            matrix_adapters[currency] = _pending(currency, adapter_type().adapter_id)
            certification_adapters[currency] = dict(matrix_adapters[currency])

    if failure is None and not args.dry_run:
        failure = {
            "currency": "ALL_REMAINING",
            "adapter_id": "PHASE13",
            "series_id": "MULTI_SOURCE",
            "failure_code": "PUBLICATION_SAFE_FULL_ADAPTER_CERTIFICATION_NOT_COMPLETED",
            "failure_stage": "PHASE13_ADAPTER_CERTIFICATION",
            "failure_disposition": "NO_EMPIRICAL_OR_MARKET_ACCESS",
            "blocking_decision": "BLOCKED_BY_OFFICIAL_RATE_ADAPTER",
        }

    all_certified = False
    status = "DRY_RUN" if args.dry_run else ("PASS" if all_certified else "FAIL")
    if args.dry_run:
        blocking_decision = "DRY_RUN"
    else:
        assert failure is not None
        blocking_decision = str(failure["blocking_decision"])
    matrix = {
        "schema_version": 1,
        "artifact_id": MATRIX_ID,
        "gate_id": GATE_ID,
        "usd_v3_certification_sha": USD_V3_CERTIFICATION_SHA,
        "certification_mode": "LIVE_OFFICIAL_BOUNDED_FAIL_FAST_VALUE_BLIND",
        "adapters": matrix_adapters,
        "all_required_adapters_certified": all_certified,
        "status": status,
    }
    certification = {
        "schema_version": 1,
        "artifact_id": ARTIFACT_ID,
        "gate_id": GATE_ID,
        "usd_v3_certification_sha": USD_V3_CERTIFICATION_SHA,
        "official_rate_provider_requests_sent": request_count,
        "request_windows": request_windows,
        "all_requested_dates_lte_2022_12_31": True,
        "source_snapshots_persisted": persisted_count,
        "numerical_rows_exposed_to_parser": 0,
        "rate_versions_persisted": 0,
        "market_provider_requests_sent": 0,
        "adapter_certifications": certification_adapters,
        "failure": failure,
        "blocking_decision": blocking_decision,
        "status": status,
    }
    eonia_audit = {
        "schema_version": 1,
        "artifact_id": EONIA_AUDIT_ID,
        "gate_id": GATE_ID,
        "required_eonia_end": "2019-09-30",
        "required_estr_start": "2019-10-01",
        "adapter_id": "ECB_EONIA_ESTR_V2",
        "eonia_request_planned": any(
            item["currency"] == "EUR" and item["series_id"] == "EONIA"
            for item in request_windows
        ),
        "estr_request_planned": any(
            item["currency"] == "EUR" and item["series_id"] == "ESTR"
            for item in request_windows
        ),
        "live_transition_test": (
            "DRY_RUN"
            if args.dry_run
            else (
                "BLOCKED_BEFORE_FULL_EONIA_ESTR_PARSE"
                if not all_certified
                else "PASS_SCHEMA_PHASE_ONLY"
            )
        ),
        "status": "DRY_RUN" if args.dry_run else ("PASS" if all_certified else "BLOCKED"),
    }
    if not args.dry_run:
        _write_artifacts(results_dir, matrix, certification, eonia_audit)
    print(json.dumps(certification, allow_nan=False, indent=2, sort_keys=True))
    return 0 if args.dry_run or all_certified else 2


if __name__ == "__main__":
    raise SystemExit(main())
