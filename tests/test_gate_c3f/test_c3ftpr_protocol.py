from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

SCRIPT_PATH = Path("scripts/run_gate_c3ftpr_protocol.py")


def _load_module():
    spec = importlib.util.spec_from_file_location("run_gate_c3ftpr_protocol", SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class TestGateC3FTPRProtocol:
    def test_protocol_freezes_quantization(self) -> None:
        module = _load_module()
        protocol = module.build_protocol()

        assert protocol["quantization"]["EURUSD"] == 100000
        assert protocol["quantization"]["GBPUSD"] == 100000
        assert protocol["quantization"]["USDJPY"] == 1000
        assert protocol["quantization"]["float_equality"] == "not used"

    def test_protocol_freezes_boundary_semantics(self) -> None:
        module = _load_module()
        protocol = module.build_protocol()

        assert protocol["intervals"]["minute"] == "[minute_start_utc, minute_start_utc + 60s)"
        assert "belongs to minute starting" in protocol["intervals"]["tick_on_minute_boundary"]
        assert protocol["no_tick_minutes"].startswith("do not forward fill")

    def test_protocol_hash_is_stable_for_same_content(self) -> None:
        module = _load_module()
        first = module.build_protocol()
        second = module.build_protocol()

        first.pop("created_at")
        second.pop("created_at")
        first.pop("protocol_hash")
        second.pop("protocol_hash")
        assert module.sha256_obj(first) == module.sha256_obj(second)
