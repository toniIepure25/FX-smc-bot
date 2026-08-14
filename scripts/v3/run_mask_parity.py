"""Observation-mask parity over the fleet panel (extends OHLC parity to provenance masks).

For every fleet unit, compares native vs tick->M1 on the canonical observation masks
(session_valid / bid_observed / ask_observed / executable_quote / is_imputed) IN ADDITION to
the already-certified OHLC/quote-precision parity. Uses the cached fleet .bi5 files (and the
on-disk canonical tick for the two reuse units); fetches only what is missing, firewalled and
paced. Fleet mask certification requires all 13 instruments PASS both OHLC and mask parity.
No strategy/P&L.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from fx_smc_bot.research.v3 import acquisition_pipeline as ap
from fx_smc_bot.research.v3 import canonical_m1 as cm
from fx_smc_bot.research.v3 import native_transport as nt
from fx_smc_bot.research.v3._hashing import canonical_hash
from fx_smc_bot.research.v3.capabilities import INSTRUMENTS
from fx_smc_bot.research.v3.firewall import V3HoldoutFirewall

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "results" / "gate_v3f"
CANON = REPO / "data" / "canonical"

PANEL: list[tuple[str, date, list[int] | None]] = [
    ("EURUSD", date(2014, 6, 10), None), ("USDJPY", date(2014, 6, 10), [13, 14]),
    ("GBPUSD", date(2011, 9, 14), [13, 14]), ("AUDUSD", date(2010, 6, 9), [13, 14]),
    ("NZDUSD", date(2017, 5, 10), [13, 14]), ("USDCAD", date(2013, 4, 10), [13, 14]),
    ("USDCHF", date(2015, 9, 9), [13, 14]), ("EURJPY", date(2016, 3, 8), [13, 14]),
    ("GBPJPY", date(2011, 3, 9), [13, 14]), ("AUDJPY", date(2016, 11, 9), [13, 14]),
    ("EURGBP", date(2012, 7, 11), [13, 14]), ("EURCHF", date(2014, 5, 14), [13, 14]),
    ("GBPCHF", date(2013, 8, 14), [13, 14]),
    ("EURUSD", date(2014, 6, 8), [21, 22]), ("EURUSD", date(2014, 6, 13), [19, 20]),
    ("EURUSD", date(2014, 3, 10), [13, 14]),
]


def _tick_url(inst: str, d: date, h: int) -> str:
    return (f"https://datafeed.dukascopy.com/datafeed/{inst}/{d.year:04d}/"
            f"{d.month - 1:02d}/{d.day:02d}/{h:02d}h_ticks.bi5")


def _fetch(fw: V3HoldoutFirewall, url: str, dest: Path, d: date) -> bytes | None:
    fw.guard_url(url)
    fw.guard_date(d, context="mask parity")
    if dest.exists() and dest.stat().st_size > 200 and dest.read_bytes()[:6] != b"<html>":
        return dest.read_bytes()
    for attempt in range(4):
        p = subprocess.run(["curl", "-sS", "--max-time", "40", "-o", str(dest),
                            "-w", "%{http_code}", url], capture_output=True, text=True)
        if p.stdout.strip() == "200" and dest.read_bytes()[:6] != b"<html>":
            time.sleep(4.0)
            return dest.read_bytes()
        time.sleep(10.0 * (attempt + 1))
    return None


def _canonical_tick(inst: str, d: date) -> list[dict[str, Any]] | None:
    import pandas as pd  # type: ignore[import-untyped]  # noqa: PLC0415

    frames = {}
    for side in ("bid", "ask"):
        pq = (CANON / inst / f"price={side}" / f"year={d.year}" / f"month={d.month:02d}"
              / f"day={d.day:02d}" / "data.parquet")
        if not pq.exists():
            return None
        frames[side] = pd.read_parquet(pq)
    m = frames["bid"].merge(frames["ask"], on="timestamp", suffixes=("_bid", "_ask"))
    return [{"timestamp": int(r.timestamp),
             "bid_open": r.open_bid, "bid_high": r.high_bid, "bid_low": r.low_bid,
             "bid_close": r.close_bid, "ask_open": r.open_ask, "ask_high": r.high_ask,
             "ask_low": r.low_ask, "ask_close": r.close_ask} for r in m.itertuples()]


def main() -> int:
    scratch = Path(sys.argv[1]) if len(sys.argv) > 1 else REPO / ".v3_scratch/fleet"
    scratch.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    fw = V3HoldoutFirewall()
    units: list[dict[str, Any]] = []
    for inst, d, hours in PANEL:
        tag = f"{inst.lower()}_{d.strftime('%Y%m%d')}"
        bid = _fetch(fw, nt.native_m1_url(inst, d, "BID"), scratch / f"{tag}_bid_native.bi5", d)
        ask = _fetch(fw, nt.native_m1_url(inst, d, "ASK"), scratch / f"{tag}_ask_native.bi5", d)
        native = nt.native_m1_day(bid, ask, inst, d) if (bid and ask) else None
        if hours is None:
            tick = _canonical_tick(inst, d)
        else:
            scale = ap.price_scale(inst)
            ticks: list[ap.Tick] = []
            ok = True
            for h in hours:
                raw = _fetch(fw, _tick_url(inst, d, h), scratch / f"{tag}_{h:02d}h_tick.bi5", d)
                if raw is None:
                    ok = False
                    break
                ticks.extend(ap.decode_bi5(raw, int(datetime(d.year, d.month, d.day,
                             tzinfo=timezone.utc).timestamp() * 1000) + h * 3600_000, scale))
            tick = ap.aggregate_m1(ticks) if (ok and ticks) else None
        if native is None or tick is None:
            units.append({"instrument": inst, "date": d.isoformat(),
                          "ohlc": "MISSING", "mask": "MISSING"})
            continue
        ohlc = nt.compare_parity(native, tick, inst)["verdict"]
        mask = cm.observation_mask_parity(native, tick, d)
        units.append({"instrument": inst, "date": d.isoformat(), "ohlc": ohlc,
                      "mask": mask["verdict"], "mask_detail": mask})
        print(f"  {inst} {d} -> OHLC={ohlc} MASK={mask['verdict']} "
              f"(nat exec={mask.get('native_executable')}/imp={mask.get('native_imputed')} "
              f"tick exec={mask.get('tick_executable')}/imp={mask.get('tick_imputed')})")

    ohlc_pass = {u["instrument"] for u in units if u["ohlc"] in ("PASS_EXACT",
                 "PASS_CANONICAL_EQUIVALENT")}
    mask_pass = {u["instrument"] for u in units if u["mask"] == "PASS"}
    all_inst = {i.symbol for i in INSTRUMENTS}
    mask_fail = [u for u in units if u["mask"] == "FAIL"]
    fleet_ok = ohlc_pass == all_inst and mask_pass == all_inst and not mask_fail
    art: dict[str, Any] = {
        "artifact_id": "V3_OBSERVATION_MASK_PARITY_V1",
        "canonical_schema": cm.canonical_schema_payload(),
        "panel_size": len(units),
        "ohlc_instruments_pass": sorted(ohlc_pass),
        "mask_instruments_pass": sorted(mask_pass),
        "mask_instruments_missing": sorted(all_inst - mask_pass),
        "mask_fail_units": [f"{u['instrument']}:{u['date']}" for u in mask_fail],
        "units": units,
        "certification": {
            "verdict": "V3_OBSERVATION_MASK_PARITY_CERTIFIED_FLEET_WIDE" if fleet_ok
                       else "OBSERVATION_MASK_PARITY_INCOMPLETE",
            "rule": "all 13 instruments PASS both OHLC and observation-mask parity; native "
                    "volume>0 observation rule certified vs tick.",
        },
        "2018_plus_market_or_outcome_files_opened": 0,
        "2018_plus_provider_requests_issued": 0,
    }
    art["parity_hash"] = canonical_hash({"units": units, "schema": art["canonical_schema"]})
    (OUT / "observation_mask_parity.json").write_text(json.dumps(art, indent=2, sort_keys=True))
    print("MASK PARITY:", art["certification"]["verdict"],
          "| ohlc", len(ohlc_pass), "/13 | mask", len(mask_pass), "/13 |",
          "missing", art["mask_instruments_missing"])
    return 0 if fleet_ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
