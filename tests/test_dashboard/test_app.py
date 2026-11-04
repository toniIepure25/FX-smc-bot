"""End-to-end smoke test for the Streamlit page.

The service and chart builders are unit-tested separately; this test catches
layout regressions (missing tabs, import-time failures, broken widget calls)
without requiring a browser.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("streamlit")

from streamlit.testing.v1 import AppTest  # noqa: E402

APP_PATH = Path(__file__).resolve().parents[2] / "dashboard" / "app.py"


def test_dashboard_default_load_has_no_exceptions() -> None:
    at = AppTest.from_file(str(APP_PATH), default_timeout=180)
    at.run()

    assert not at.exception, [str(exc) for exc in at.exception]
    assert len(at.tabs) == 5
    assert len(at.get("plotly_chart")) >= 5
