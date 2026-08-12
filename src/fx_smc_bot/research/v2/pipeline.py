"""End-to-end V2 dry-run pipeline (machinery verification only).

Runs spec -> signal -> execution -> costs -> daily returns -> statistics -> survivor
classification on permitted/synthetic fixtures. Its sole purpose is to prove the pipeline
is wired correctly and deterministic. No dry-run result may influence the frozen V2 search
space, statistical protocol or survivor predicate.
"""

from __future__ import annotations

from typing import Any

import pandas as pd  # type: ignore[import-untyped]

from fx_smc_bot.research.v2 import statistics as stats
from fx_smc_bot.research.v2.kernel import evaluate
from fx_smc_bot.research.v2.signals import generate_signal
from fx_smc_bot.research.v2.spec import StrategySpec
from fx_smc_bot.research.v2.survivor import is_scientific_survivor


def select_dry_run_specs(specs: list[StrategySpec], per_family: int = 2) -> list[StrategySpec]:
    """Deterministically pick a small representative subset covering every family."""

    by_family: dict[str, list[StrategySpec]] = {}
    for spec in specs:
        by_family.setdefault(spec.family_id, []).append(spec)
    selected: list[StrategySpec] = []
    for family in sorted(by_family):
        ordered = sorted(by_family[family], key=lambda s: s.spec_hash())
        selected.extend(ordered[:per_family])
    return selected


def evaluate_spec(spec: StrategySpec, frame: pd.DataFrame) -> dict[str, Any]:
    signal = generate_signal(frame, spec)
    result = evaluate(frame, signal, spec)
    base = result["by_multiplier"]["1.0x"]
    return {
        "family_id": spec.family_id,
        "instrument": spec.instrument,
        "spec_hash": spec.spec_hash(),
        "trade_count": int(base["trade_count"]),
        "net_bps": float(base["net_bps"]),
        "sharpe": float(base["daily_sharpe"]),
        "active_days": int(base["days"]),
        "survives_1_5x": float(result["by_multiplier"]["1.5x"]["net_bps"]) > 0.0,
        "survives_2_0x": float(result["by_multiplier"]["2.0x"]["net_bps"]) > 0.0,
        "nonzero_signal_bars": int((signal != 0).sum()),
        "base_daily_net_bps": result["base_daily_net_bps"],
    }


def dry_run(specs: list[StrategySpec], frames: dict[str, pd.DataFrame]) -> dict[str, Any]:
    """Execute the full pipeline for a subset of specs over per-instrument frames."""

    rows: list[dict[str, Any]] = []
    series_parts: list[pd.Series] = []
    for spec in specs:
        frame = frames[spec.instrument]
        evaluated = evaluate_spec(spec, frame)
        series = evaluated.pop("base_daily_net_bps")
        if len(series):
            series_parts.append(series.rename(evaluated["spec_hash"][:12]))
        rows.append(evaluated)

    if series_parts:
        matrix = pd.concat(series_parts, axis=1).fillna(0.0)
    else:
        matrix = pd.DataFrame()
    seed = 1729
    bootstrap = stats.bootstrap_family_stats(matrix, seed=seed) if not matrix.empty else {}
    pbo = stats.pbo_cscv(matrix)

    survivor_rows: list[dict[str, Any]] = []
    for row in rows:
        candidate = {
            "net_bps": row["net_bps"],
            "sharpe": row["sharpe"],
            "trade_count": row["trade_count"],
            "active_days": row["active_days"],
            "fold_positive_fraction": 0.0,
            "instrument_loo_positive": False,
            "neighborhood_same_sign_fraction": 0.0,
            "survives_1_5x": row["survives_1_5x"],
            "survives_2_0x": row["survives_2_0x"],
            "romano_wolf_p": 1.0,
            "pbo": pbo.get("pbo", "NOT_APPLICABLE"),
            "holdout_clean": True,
            "reproduction_pass": True,
        }
        is_survivor, failed = is_scientific_survivor(candidate)
        survivor_rows.append({"spec_hash": row["spec_hash"], "survivor": is_survivor,
                              "failed_requirements": failed})

    ran_ok = all(
        isinstance(row["net_bps"], float) and row["active_days"] >= 0 for row in rows
    )
    return {
        "artifact_id": "A0R4_DRY_RUN_V1",
        "purpose": "pipeline_verification_only_not_alpha_discovery",
        "evaluated_specs": len(rows),
        "families_covered": sorted({row["family_id"] for row in rows}),
        "all_stages_executed": bool(ran_ok),
        "multiple_testing": bootstrap,
        "pbo": pbo,
        "scientific_survivor_count": sum(1 for r in survivor_rows if r["survivor"]),
        "per_spec": [{k: v for k, v in row.items() if k != "base_daily_net_bps"} for row in rows],
        "survivor_evaluation": survivor_rows,
        "note": "Synthetic/permitted fixtures only; results never feed the frozen V2 design.",
    }
