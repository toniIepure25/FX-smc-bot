"""End-to-end pipeline integration: spec -> compile -> materialize -> dry run."""

from __future__ import annotations

from fx_smc_bot.research.v2.compiler import ADMITTED, compile_all
from fx_smc_bot.research.v2.materialize import materialize
from fx_smc_bot.research.v2.pipeline import dry_run, select_dry_run_specs
from fx_smc_bot.research.v2.search_space import enumerate_admitted_specs
from fx_smc_bot.research.v2.synthetic import synthetic_frame


def test_full_pipeline_executes_all_stages_and_is_deterministic() -> None:
    admitted, _ = compile_all(enumerate_admitted_specs())
    specs = [r.spec for r in admitted if r.terminal_state == ADMITTED]
    # materialization sanity
    trials = materialize(admitted, git_sha="test")
    assert len(trials) == len(specs)

    dry_specs = select_dry_run_specs(specs, per_family=1)
    frames = {inst: synthetic_frame(inst, n_bars=1500) for inst in
              {s.instrument for s in dry_specs}}
    out_a = dry_run(dry_specs, frames)
    out_b = dry_run(dry_specs, frames)

    assert out_a["all_stages_executed"]
    assert len(out_a["families_covered"]) == 8  # all admitted families exercised
    # deterministic per-spec economics
    a = {r["spec_hash"]: r["net_bps"] for r in out_a["per_spec"]}
    b = {r["spec_hash"]: r["net_bps"] for r in out_b["per_spec"]}
    assert a == b
    # dry run never claims survivors on random-walk noise
    assert out_a["scientific_survivor_count"] == 0


def test_select_dry_run_specs_covers_every_family_deterministically() -> None:
    admitted, _ = compile_all(enumerate_admitted_specs())
    specs = [r.spec for r in admitted if r.terminal_state == ADMITTED]
    first = [s.spec_hash() for s in select_dry_run_specs(specs, per_family=2)]
    second = [s.spec_hash() for s in select_dry_run_specs(specs, per_family=2)]
    assert first == second
