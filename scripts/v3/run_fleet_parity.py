"""Fleet-wide native-M1 vs tick->M1 parity panel + transport certification.

Firewalled, paced (503-backoff) acquisition of a stratified pre-2018 panel covering all 13 V3
instruments, both scaling classes (JPY/non-JPY), majors and crosses, early and late epochs,
and every FX session class (full / Sunday-open / Friday-close / DST-adjacent). Each unit is
compared under the already-frozen quote-precision parity contract; no post-result tolerance
change and no strategy/P&L. Certifies V3_NATIVE_M1_BULK_TRANSPORT_CERTIFIED_FLEET_WIDE only
when the coverage requirements are met AND there are zero material FAILs.
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
from fx_smc_bot.research.v3 import native_transport as nt
from fx_smc_bot.research.v3._hashing import canonical_hash
from fx_smc_bot.research.v3.acquisition_pipeline import is_jpy
from fx_smc_bot.research.v3.capabilities import INSTRUMENTS
from fx_smc_bot.research.v3.firewall import V3HoldoutFirewall
from fx_smc_bot.research.v3.fx_calendar import classify_session, session_window_utc

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "results" / "gate_v3f"
CANON = REPO / "data" / "canonical"

# (instrument, date, epoch_tag, tick_hours). Full-day units use liquid 13-14 UTC; session
# specials use hours straddling their boundary. Units 1-2 reuse the on-disk certified canonical.
FULL = "full"
PANEL: list[tuple[str, date, str, list[int] | None]] = [
    ("EURUSD", date(2014, 6, 10), "mid", None),               # reuse canonical (non-JPY major)
    ("USDJPY", date(2014, 6, 10), "mid", None),               # reuse canonical (JPY major)
    ("GBPUSD", date(2011, 9, 14), "early", [13, 14]),
    ("AUDUSD", date(2010, 6, 9), "early", [13, 14]),
    ("NZDUSD", date(2017, 5, 10), "late", [13, 14]),
    ("USDCAD", date(2013, 4, 10), "mid", [13, 14]),
    ("USDCHF", date(2015, 9, 9), "late", [13, 14]),
    ("EURJPY", date(2016, 3, 8), "late", [13, 14]),
    ("GBPJPY", date(2011, 3, 9), "early", [13, 14]),
    ("AUDJPY", date(2016, 11, 9), "late", [13, 14]),
    ("EURGBP", date(2012, 7, 11), "mid", [13, 14]),
    ("EURCHF", date(2014, 5, 14), "mid", [13, 14]),
    ("GBPCHF", date(2013, 8, 14), "mid", [13, 14]),
    ("EURUSD", date(2014, 6, 8), "sunday_open", [21, 22]),    # Sunday partial (EDT open 21:00)
    ("EURUSD", date(2014, 6, 13), "friday_close", [19, 20]),  # Friday partial (EDT close 21:00)
    ("EURUSD", date(2014, 3, 10), "dst_adjacent", [13, 14]),  # Mon after 2014-03-09 spring fwd
]

INTER_REQUEST_S = 4.0
MAX_RETRIES = 4


def native_url(inst: str, d: date, side: str) -> str:
    return nt.native_m1_url(inst, d, side)


def tick_url(inst: str, d: date, hour: int) -> str:
    return (f"https://datafeed.dukascopy.com/datafeed/{inst}/{d.year:04d}/"
            f"{d.month - 1:02d}/{d.day:02d}/{hour:02d}h_ticks.bi5")


def curl(url: str, dest: Path) -> tuple[int, int]:
    p = subprocess.run(["curl", "-sS", "--max-time", "40", "-o", str(dest),
                        "-w", "%{http_code} %{size_download}", url], capture_output=True, text=True)
    parts = p.stdout.strip().split()
    return (int(parts[0]), int(parts[1])) if len(parts) == 2 and parts[0].isdigit() else (-1, 0)


def fetch(fw: V3HoldoutFirewall, url: str, dest: Path, d: date) -> bytes | None:
    """Firewalled, backing-off fetch. Returns bytes on 200, None otherwise (cached if present)."""

    fw.guard_url(url)
    fw.guard_date(d, context="fleet parity")
    if dest.exists() and dest.stat().st_size > 200 and dest.read_bytes()[:6] != b"<html>":
        return dest.read_bytes()
    for attempt in range(MAX_RETRIES):
        status, size = curl(url, dest)
        if status == 200 and dest.exists() and dest.read_bytes()[:6] != b"<html>":
            time.sleep(INTER_REQUEST_S)
            return dest.read_bytes()
        if status in (429, 503, -1):
            time.sleep(10.0 * (attempt + 1))
            continue
        break
    time.sleep(INTER_REQUEST_S)
    return None


def day_ms(d: date) -> int:
    return int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp() * 1000)


def tick_ref_from_canonical(inst: str, d: date) -> list[dict[str, Any]] | None:
    import pandas as pd  # type: ignore[import-untyped]  # noqa: PLC0415

    frames = {}
    for side in ("bid", "ask"):
        pq = (CANON / inst / f"price={side}" / f"year={d.year}" / f"month={d.month:02d}"
              / f"day={d.day:02d}" / "data.parquet")
        if not pq.exists():
            return None
        frames[side] = pd.read_parquet(pq)
    b, a = frames["bid"], frames["ask"]
    m = b.merge(a, on="timestamp", suffixes=("_bid", "_ask"))
    return [{"timestamp": int(r.timestamp),
             "bid_open": r.open_bid, "bid_high": r.high_bid, "bid_low": r.low_bid,
             "bid_close": r.close_bid, "ask_open": r.open_ask, "ask_high": r.high_ask,
             "ask_low": r.low_ask, "ask_close": r.close_ask} for r in m.itertuples()]


def main() -> int:
    scratch = Path(sys.argv[1]) if len(sys.argv) > 1 else REPO / ".v3_scratch"
    scratch.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    fw = V3HoldoutFirewall()
    units: list[dict[str, Any]] = []

    for inst, d, epoch, tick_hours in PANEL:
        tag = f"{inst.lower()}_{d.strftime('%Y%m%d')}"
        bid_raw = fetch(fw, native_url(inst, d, "BID"), scratch / f"{tag}_bid_native.bi5", d)
        ask_raw = fetch(fw, native_url(inst, d, "ASK"), scratch / f"{tag}_ask_native.bi5", d)
        native = nt.native_m1_day(bid_raw, ask_raw, inst, d) if (bid_raw and ask_raw) else None

        if tick_hours is None:
            tick = tick_ref_from_canonical(inst, d)
        else:
            scale = ap.price_scale(inst)
            ticks: list[ap.Tick] = []
            ok = True
            for h in tick_hours:
                raw = fetch(fw, tick_url(inst, d, h), scratch / f"{tag}_{h:02d}h_tick.bi5", d)
                if raw is None:
                    ok = False
                    break
                ticks.extend(ap.decode_bi5(raw, day_ms(d) + h * 3600_000, scale))
            tick = ap.aggregate_m1(ticks) if (ok and ticks) else None

        result = nt.compare_parity(native, tick, inst)
        # session-coverage metadata: native's covered window vs the calendar contract
        win = session_window_utc(d)
        native_cov = None
        if native:
            ts = [r["timestamp"] for r in native]
            _iso = lambda ms: datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat()  # noqa: E731
            native_cov = {"first": _iso(min(ts)), "last": _iso(max(ts)), "rows": len(native)}
        units.append({
            "instrument": inst, "date": d.isoformat(), "epoch": epoch,
            "session_class": classify_session(d), "jpy": is_jpy(inst),
            "expected_window_utc": [win[0].isoformat(), win[1].isoformat()] if win else None,
            "native_coverage": native_cov, **result,
        })
        print(f"  {inst} {d} [{classify_session(d)}/{epoch}] -> {result['verdict']} "
              f"shared={result.get('shared_minutes')} "
              f"precmis={result.get('precision_field_mismatches')}")

    _pass = (nt.PARITY_PASS_EXACT, nt.PARITY_PASS_CANONICAL)
    present = [u for u in units if u["verdict"] in (*_pass, nt.PARITY_FAIL)]
    passed = [u for u in present if u["verdict"] in _pass]
    failed = [u for u in present if u["verdict"] == nt.PARITY_FAIL]

    covered_instruments = {u["instrument"] for u in passed}
    all_instruments = {i.symbol for i in INSTRUMENTS}
    session_classes = {u["session_class"] for u in passed}
    has_jpy = any(u["jpy"] for u in passed)
    has_nonjpy = any(not u["jpy"] for u in passed)
    fleet_ok = (
        covered_instruments == all_instruments
        and has_jpy and has_nonjpy
        and {"FULL_SESSION", "PARTIAL_SUNDAY_OPEN", "PARTIAL_FRIDAY_CLOSE"} <= session_classes
        and len(failed) == 0
    )

    panel: dict[str, Any] = {
        "artifact_id": "V3_NATIVE_PARITY_PANEL_FLEET_V1",
        "parity_contract": nt.parity_contract(),
        "panel_size": len(units),
        "units_with_both_transports": len(present),
        "pass_units": len(passed),
        "fail_units": len(failed),
        "instruments_covered": sorted(covered_instruments),
        "instruments_missing": sorted(all_instruments - covered_instruments),
        "session_classes_covered": sorted(session_classes),
        "jpy_covered": has_jpy, "nonjpy_covered": has_nonjpy,
        "verdict_counts": {v: sum(1 for u in units if u["verdict"] == v)
                           for v in {u["verdict"] for u in units}},
        "units": units,
        "transport_certification": {
            "verdict": "V3_NATIVE_M1_BULK_TRANSPORT_CERTIFIED_FLEET_WIDE" if fleet_ok
                       else "NATIVE_M1_FLEET_NOT_CERTIFIED",
            "rule": "certify fleet-wide only if all 13 instruments pass, both scaling classes "
                    "pass, full/Sunday-open/Friday-close session classes pass, and zero FAIL "
                    "under the frozen quote-precision contract.",
            "native_primary": fleet_ok,
            "tick_fallback_role": "deterministic per-day fallback only" if fleet_ok else "primary",
        },
        "2018_plus_market_or_outcome_files_opened": 0,
        "2018_plus_provider_requests_issued": 0,
    }
    panel["panel_hash"] = canonical_hash({"units": units, "contract": panel["parity_contract"]})
    (OUT / "native_parity_panel.json").write_text(json.dumps(panel, indent=2, sort_keys=True))
    print("FLEET verdict:", panel["transport_certification"]["verdict"],
          "| pass", len(passed), "fail", len(failed),
          "| instruments", len(covered_instruments), "/ 13",
          "| missing", panel["instruments_missing"])
    return 0 if fleet_ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
