from __future__ import annotations

from datetime import date
from pathlib import Path

from fx_smc_bot.research import quant_polarity_execution, quant_polarity_q0r_data


def test_execution_loader_routes_to_q0r_capability(monkeypatch) -> None:
    sentinel = object()
    monkeypatch.setenv("FX_Q0R_EXECUTION", "1")
    monkeypatch.setattr(
        quant_polarity_q0r_data,
        "load_q0r_development_m5_window",
        lambda *_args: sentinel,
    )
    result = quant_polarity_execution.load_development_m5_window(
        Path("repository"), "AUDUSD", date(2015, 1, 1), date(2015, 1, 2)
    )
    assert result is sentinel


def test_q0r_ledgers_are_outside_repository(tmp_path, monkeypatch) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    clean_root = tmp_path / "clean"
    clean_root.mkdir()
    monkeypatch.setenv("FX_Q0R_EXECUTION", "1")
    monkeypatch.setenv("FX_Q0R_DATA_ROOT", str(clean_root))
    ledger, metadata = quant_polarity_execution._development_ledger_paths(
        repository, "SMC_A_SWEEP_REVERSAL_V1", 2015
    )
    assert clean_root in ledger.parents
    assert clean_root in metadata.parents
    assert repository not in ledger.parents
    assert "gate_q0r" in ledger.parts
