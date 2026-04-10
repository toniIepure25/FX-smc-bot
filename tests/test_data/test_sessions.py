"""Tests for session labeling."""

from __future__ import annotations

from datetime import datetime

import numpy as np

from fx_smc_bot.config import SessionConfig
from fx_smc_bot.data.sessions import label_sessions
from fx_smc_bot.domain import SessionName


class TestSessionLabeling:
    def test_asian_session(self) -> None:
        ts = np.array([np.datetime64("2024-01-02T03:00")], dtype="datetime64[ns]")
        labels = label_sessions(ts)
        assert labels[0] == SessionName.ASIAN

    def test_london_session(self) -> None:
        ts = np.array([np.datetime64("2024-01-02T09:00")], dtype="datetime64[ns]")
        labels = label_sessions(ts)
        assert labels[0] == SessionName.LONDON

    def test_new_york_session(self) -> None:
        ts = np.array([np.datetime64("2024-01-02T17:00")], dtype="datetime64[ns]")
        labels = label_sessions(ts)
        assert labels[0] == SessionName.NEW_YORK

    def test_overlap_session(self) -> None:
        ts = np.array([np.datetime64("2024-01-02T13:00")], dtype="datetime64[ns]")
        labels = label_sessions(ts)
        assert labels[0] == SessionName.LONDON_NY_OVERLAP

    def test_multiple_timestamps(self) -> None:
        ts = np.array([
            np.datetime64("2024-01-02T02:00"),
            np.datetime64("2024-01-02T10:00"),
            np.datetime64("2024-01-02T14:00"),
            np.datetime64("2024-01-02T18:00"),
        ], dtype="datetime64[ns]")
        labels = label_sessions(ts)
        assert labels[0] == SessionName.ASIAN
        assert labels[1] == SessionName.LONDON
        assert labels[2] == SessionName.LONDON_NY_OVERLAP
        assert labels[3] == SessionName.NEW_YORK
