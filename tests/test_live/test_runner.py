"""Tests for PaperTradingRunner end-to-end flow."""

from __future__ import annotations

from pathlib import Path

import pytest

from fx_smc_bot.config import AppConfig
from fx_smc_bot.live.runner import PaperTradingRunner
from fx_smc_bot.live.state import LiveState
from tests.helpers import make_synthetic_data


class TestPaperTradingRunner:
    def test_runner_produces_state(self, tmp_path: Path) -> None:
        config = AppConfig()
        data = make_synthetic_data()
        runner = PaperTradingRunner(config, output_dir=tmp_path)
        state = runner.run(data)

        assert isinstance(state, LiveState)
        assert state.bars_processed > 0
        assert state.equity > 0
        assert state.run_id == runner.run_id

    def test_runner_creates_journal(self, tmp_path: Path) -> None:
        config = AppConfig()
        data = make_synthetic_data()
        runner = PaperTradingRunner(config, output_dir=tmp_path)
        runner.run(data)

        journal_path = tmp_path / runner.run_id / "journal.jsonl"
        assert journal_path.exists()
        content = journal_path.read_text()
        assert "run_start" in content

    def test_runner_creates_state_file(self, tmp_path: Path) -> None:
        config = AppConfig()
        data = make_synthetic_data()
        runner = PaperTradingRunner(config, output_dir=tmp_path)
        runner.run(data)

        state_path = tmp_path / runner.run_id / "state.json"
        assert state_path.exists()
        loaded = LiveState.load(state_path)
        assert loaded.run_id == runner.run_id
