from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

SCRIPT_PATH = Path("scripts/run_gate_c3fta_blocker_analysis.py")


def _load_module():
    spec = importlib.util.spec_from_file_location("run_gate_c3fta_blocker_analysis", SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class TestGateC3FTABlockerAnalysis:
    def test_frozen_plan_is_not_substituted_by_generated_candidate(self) -> None:
        module = _load_module()
        proof, frozen_plan = module.prove_frozen_plan()

        assert proof.blocker_code == "FROZEN_PLAN_MISSING"
        assert proof.documented_plan_hash == "bbcebd0b6cc0"
        assert proof.generated_candidate_hash == "bbcebd0b6cc0"
        assert proof.placeholder_file_hash != proof.generated_candidate_hash
        assert frozen_plan["status"] == "FROZEN_PLAN_NOT_PROVEN"
        assert frozen_plan["windows"] == []
        assert frozen_plan["do_not_execute_generated_candidate"] is True

    def test_first_2019_placeholder_window_mismatches_documented_generator(self) -> None:
        module = _load_module()
        proof, _ = module.prove_frozen_plan()
        mismatch = proof.structured_error

        assert mismatch["mismatch"] is True
        assert mismatch["placeholder_window"]["week_start"] == "2019-02-11"
        assert mismatch["generated_candidate_window"]["week_start"] == "2019-03-18"
        assert mismatch["access_implementation_or_scientific"] == "implementation"

    def test_event_blocked_artifact_has_no_forbidden_metric_fields(self) -> None:
        module = _load_module()
        event_artifact = module.blocked_result(
            "2019_event_funnels.json",
            {"funnels": {}, "forbidden_metric_fields_present": False},
        )

        assert not module.contains_forbidden_performance_fields(event_artifact)

    def test_protocol_hash_is_stable(self) -> None:
        module = _load_module()
        first = module.tick_to_m1_protocol()
        second = module.tick_to_m1_protocol()

        assert first["protocol_hash"] == second["protocol_hash"]
        assert first["integer_quantization"]["EURUSD"] == 100000
        assert first["integer_quantization"]["USDJPY"] == 1000
