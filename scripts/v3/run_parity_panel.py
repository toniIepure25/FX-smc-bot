"""Evaluate the stratified native-M1 vs tick->M1 parity panel and decide transport certification.

Applies the frozen parity contract (native_transport.parity_contract) to each panel unit and
writes results/gate_v3f/native_parity_panel.json plus a transport-certification artifact.
Native raw files come from the scratch fetch; tick references come either from the certified
on-disk canonical (units reusing last session's sample) or from freshly fetched hourly ticks.
No strategy/P&L is computed.
"""

from __future__ import annotations

import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd  # type: ignore[import-untyped]

from fx_smc_bot.research.v3 import acquisition_pipeline as ap
from fx_smc_bot.research.v3 import native_transport as nt
from fx_smc_bot.research.v3._hashing import canonical_hash

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "results" / "gate_v3f"
CANON = REPO / "data" / "canonical"

# Panel definition: (instrument, date, session_type, tick_source)
#   tick_source = "canonical" (reuse on-disk certified sample) | ("ticks", [hours])
PANEL = [
    ("EURUSD", date(2014, 6, 10), "nonjpy_major_london_ny", ("canonical", None)),
    ("USDJPY", date(2014, 6, 10), "jpy_major_london_ny", ("canonical", None)),
    ("EURJPY", date(2016, 3, 8), "jpy_cross_later_year", ("ticks", [9, 10, 11])),
    ("GBPUSD", date(2011, 9, 14), "nonjpy_major_early_year", ("ticks", [9, 10, 11])),
]


def _day_ms(d: date) -> int:
    return int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp() * 1000)


def _valid_bi5(p: Path) -> bytes | None:
    if not p.exists() or p.stat().st_size < 200:
        return None
    raw = p.read_bytes()
    return None if raw[:6] == b"<html>" else raw


def _native_rows(scratch: Path, inst: str, d: date) -> list[dict[str, Any]] | None:
    bid = _valid_bi5(scratch / f"{inst.lower()}_{d.strftime('%Y%m%d')}_bid_native.bi5")
    ask = _valid_bi5(scratch / f"{inst.lower()}_{d.strftime('%Y%m%d')}_ask_native.bi5")
    if bid is None or ask is None:
        return None
    return nt.native_m1_day(bid, ask, inst, d)


def _tick_rows_from_canonical(inst: str, d: date) -> list[dict[str, Any]] | None:
    base = CANON / inst
    frames = {}
    for side in ("bid", "ask"):
        pq = (base / f"price={side}" / f"year={d.year}" / f"month={d.month:02d}"
              / f"day={d.day:02d}" / "data.parquet")
        if not pq.exists():
            return None
        frames[side] = pd.read_parquet(pq)
    b, a = frames["bid"], frames["ask"]
    merged = pd.merge(b, a, on="timestamp", suffixes=("_bid", "_ask"))
    return [{"timestamp": int(r.timestamp),
             "bid_open": r.open_bid, "bid_high": r.high_bid, "bid_low": r.low_bid,
             "bid_close": r.close_bid,
             "ask_open": r.open_ask, "ask_high": r.high_ask, "ask_low": r.low_ask,
             "ask_close": r.close_ask} for r in merged.itertuples()]


def _tick_rows_from_ticks(scratch: Path, inst: str, d: date, hours: list[int]
                          ) -> list[dict[str, Any]] | None:
    scale = ap.price_scale(inst)
    ticks: list[ap.Tick] = []
    for h in hours:
        raw = _valid_bi5(scratch / f"{inst.lower()}_{d.strftime('%Y%m%d')}_{h:02d}h_tick.bi5")
        if raw is None:
            return None
        hour_ms = _day_ms(d) + h * 3600_000
        ticks.extend(ap.decode_bi5(raw, hour_ms, scale))
    return ap.aggregate_m1(ticks) if ticks else None


def main() -> int:
    scratch = Path(sys.argv[1]) if len(sys.argv) > 1 else REPO / ".v3_scratch"
    # EURUSD BID native was fetched to a differently-named file earlier; normalize.
    legacy = scratch / "eur_20140610_bid_m1.bi5"
    target = scratch / "eurusd_20140610_bid_native.bi5"
    if legacy.exists() and not target.exists():
        target.write_bytes(legacy.read_bytes())

    units = []
    for inst, d, session, (kind, hours) in PANEL:
        native = _native_rows(scratch, inst, d)
        if kind == "canonical":
            tick = _tick_rows_from_canonical(inst, d)
        else:
            tick = _tick_rows_from_ticks(scratch, inst, d, hours or [])
        result = nt.compare_parity(native, tick, inst)
        units.append({"instrument": inst, "date": d.isoformat(), "session_type": session,
                      "tick_source": kind, **result})
        print(f"  {inst} {d} [{session}] -> {result['verdict']} "
              f"(shared={result.get('shared_minutes')}, "
              f"precision_mismatch={result.get('precision_field_mismatches')})")

    _pass = (nt.PARITY_PASS_EXACT, nt.PARITY_PASS_CANONICAL)
    present = [u for u in units if u["verdict"] in (*_pass, nt.PARITY_FAIL)]
    passed = [u for u in present if u["verdict"] in _pass]
    failed = [u for u in present if u["verdict"] == nt.PARITY_FAIL]
    certified = len(present) >= 2 and len(failed) == 0

    panel: dict[str, Any] = {
        "artifact_id": "V3_NATIVE_PARITY_PANEL_V1",
        "parity_contract": nt.parity_contract(),
        "panel_size": len(units),
        "units_with_both_transports": len(present),
        "pass_units": len(passed),
        "fail_units": len(failed),
        "verdict_counts": {v: sum(1 for u in units if u["verdict"] == v)
                           for v in {u["verdict"] for u in units}},
        "units": units,
        "transport_certification": {
            "verdict": "V3_NATIVE_M1_BULK_TRANSPORT_CERTIFIED" if certified
                       else "NATIVE_M1_NOT_CERTIFIED_RETAIN_TICK",
            "rule": "certify only if >=2 units have both transports AND zero FAIL under the "
                    "frozen quote-precision contract.",
            "native_primary": certified,
            "tick_fallback_role": "deterministic per-day fallback only" if certified
                                  else "primary (native not certified)",
        },
        "2018_plus_market_or_outcome_files_opened": 0,
        "2018_plus_provider_requests_issued": 0,
    }
    panel["panel_hash"] = canonical_hash({"units": units, "contract": panel["parity_contract"]})
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "native_parity_panel.json").write_text(json.dumps(panel, indent=2, sort_keys=True))
    print("transport verdict:", panel["transport_certification"]["verdict"],
          "| pass", len(passed), "fail", len(failed), "of", len(present), "present")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
