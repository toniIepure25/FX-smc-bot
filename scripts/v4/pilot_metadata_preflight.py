"""V4 Pilot Metadata Preflight - Databento GLBX.MDP3 MBP-10.
METADATA ONLY. No historical market data download. No timeseries. No batch.
Usage:
    python pilot_metadata_preflight.py --manifest <path> --metadata-only --dry-run
    python pilot_metadata_preflight.py --manifest <path> --metadata-only --emit-commands
    python pilot_metadata_preflight.py --manifest <path> --metadata-only --output <path>
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# FIREWALL: No historical market data endpoints are importable or callable.
# ---------------------------------------------------------------------------

FORBIDDEN_METHODS = frozenset({
    "get_range", "get_subscription", "batch", "download",
    "timeseries", "replay", "to_df", "to_ndarray",
})


def _guard_against_market_data() -> None:
    """Ensure no market data download path is reachable."""
    for mod_name in ("databento",):
        if mod_name in sys.modules:
            mod = sys.modules[mod_name]
            for attr in dir(mod):
                if attr.lower() in FORBIDDEN_METHODS:
                    raise RuntimeError(
                        f"FORBIDDEN: {mod_name}.{attr} is a market-data endpoint. "
                        f"Preflight is metadata-only."
                    )


def load_manifest(path: str) -> dict:
    with open(path) as f:
        return json.load(f)


def group_by_instrument_date(manifest: dict) -> list[dict]:
    """Group manifest entries for metadata queries."""
    entries = manifest["entries"]
    groups: dict[str, list[dict]] = {}
    for e in entries:
        key = f"{e['instrument']}|{e['date']}"
        groups.setdefault(key, []).append(e)
    return [
        {"instrument": g[0]["instrument"], "date": g[0]["date"],
         "contract": g[0]["contract"], "role": g[0]["role"]}
        for g in groups.values()
    ]


def emit_commands(groups: list[dict]) -> list[str]:
    """Emit exact Databento metadata commands for each instrument-day."""
    cmds = []
    for g in groups:
        d = g["date"]
        contract = g["contract"]
        cmds.append(
            f"client.metadata.get_record_count(dataset='GLBX.MDP3', "
            f"symbols=['{contract}'], schema='mbp-10', "
            f"start='{d}T00:00', end='{d}T23:59')"
        )
        cmds.append(
            f"client.metadata.get_billable_size(dataset='GLBX.MDP3', "
            f"symbols=['{contract}'], schema='mbp-10', "
            f"start='{d}T00:00', end='{d}T23:59')"
        )
        cmds.append(
            f"client.metadata.get_cost(dataset='GLBX.MDP3', "
            f"symbols='{contract}', schema='mbp-10', "
            f"start='{d}', end='{d}')"
        )
    return cmds


def run_preflight(manifest_path: str, output_path: str | None) -> dict:
    """Run metadata-only preflight. Returns result dict."""
    _guard_against_market_data()
    manifest = load_manifest(manifest_path)
    groups = group_by_instrument_date(manifest)

    api_key = os.environ.get("DATABENTO_API_KEY", "")
    has_key = bool(api_key)

    result = {
        "manifest_hash": manifest["manifest_hash"],
        "total_instrument_days": manifest["total_instrument_days"],
        "by_role": manifest["by_role"],
        "by_instrument": manifest["by_instrument"],
        "api_key_present": has_key,
    }

    if not has_key:
        result["status"] = "BLOCKED_BY_API_CREDENTIAL"
        result["commands"] = emit_commands(groups)
        result["note"] = (
            "No DATABENTO_API_KEY found. Set the environment variable and "
            "re-run this script. No estimates are fabricated."
        )
    else:
        # When key is present, actual metadata calls would go here.
        # For now, emit commands (actual API calls require the databento package).
        result["status"] = "COMMANDS_READY"
        result["commands"] = emit_commands(groups)
        result["note"] = (
            "API key present. Commands emitted. Run with the databento "
            "package installed to execute actual metadata calls."
        )

    if output_path:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_text(json.dumps(result, indent=1))
        print(f"wrote {output_path}")

    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="V4 Pilot Metadata Preflight (metadata only)"
    )
    parser.add_argument("--manifest", required=True, help="Path to P1 manifest JSON")
    parser.add_argument("--metadata-only", action="store_true",
                        help="Assert metadata-only mode (always enforced)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Emit commands without executing")
    parser.add_argument("--emit-commands", action="store_true",
                        help="Print exact commands to stdout")
    parser.add_argument("--output", default=None, help="Output JSON path")
    args = parser.parse_args()

    # Firewall: always metadata-only
    _guard_against_market_data()

    result = run_preflight(args.manifest, args.output)

    if args.emit_commands or args.dry_run:
        for cmd in result.get("commands", []):
            print(cmd)

    print(f"\nstatus: {result['status']}")
    print(f"instrument-days: {result['total_instrument_days']}")
    print(f"api_key: {'present' if result['api_key_present'] else 'MISSING'}")


if __name__ == "__main__":
    main()
