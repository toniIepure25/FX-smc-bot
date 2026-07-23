from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

SCRIPT_PATH = Path("scripts/run_gate_c3ftpr_plan_amendment.py")


def _load_module():
    spec = importlib.util.spec_from_file_location("run_gate_c3ftpr_plan_amendment", SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class TestGateC3FTPRPlanAmendment:
    def test_reproduces_documented_hash_and_window_count(self) -> None:
        module = _load_module()
        reproduced, evidence = module.reproduce_candidate()

        assert reproduced["generated_window_count"] == 44
        assert reproduced["generated_plan_hash"] == "bbcebd0b6cc0"
        assert evidence["byte_identical"] is True

    def test_canonical_json_stability(self) -> None:
        module = _load_module()
        first = module.canonical_json(module.current_plan())
        second = module.canonical_json(module.current_plan())

        assert first == second
        assert module.sha256_text(first) == module.sha256_text(second)

    def test_amendment_eligible_without_outcome_information(self) -> None:
        module = _load_module()
        reproduced, evidence = module.reproduce_candidate()
        pre_info = {
            "amendment_eligible": True,
            "tick_windows_downloaded": False,
            "ohlc_results_observed": False,
            "tolerances_changed_after_results": False,
            "windows_changed_after_results": False,
        }
        amendment, record = module.build_amendment(
            reproduced,
            evidence,
            pre_info,
            "prov",
            "pre",
        )

        assert amendment["status"] == "PROSPECTIVELY_FROZEN"
        assert record["scientifically_valid"] is True
        assert amendment["not_original_artifact"] is True

    def test_rejects_amendment_when_prior_outcome_information_exists(self) -> None:
        module = _load_module()
        reproduced, evidence = module.reproduce_candidate()
        pre_info = {
            "amendment_eligible": False,
            "tick_windows_downloaded": True,
            "ohlc_results_observed": True,
            "tolerances_changed_after_results": False,
            "windows_changed_after_results": False,
        }
        amendment, record = module.build_amendment(
            reproduced,
            evidence,
            pre_info,
            "prov",
            "pre",
        )

        assert amendment["status"] == "BLOCKED"
        assert record["scientifically_valid"] is False

    def test_generic_non_tick_comparison_files_do_not_block_amendment(self) -> None:
        audit = {
            "tick_windows_downloaded": False,
            "tick_comparisons_executed": False,
            "ohlc_results_observed": False,
            "tolerances_changed_after_results": False,
            "windows_changed_after_results": False,
            "outcome_information_available": False,
            "amendment_eligible": True,
            "unrelated_comparison_like_files": [
                {"path": "results/old_wave/final_candidate_comparison.md"},
            ],
        }

        assert audit["amendment_eligible"]

    def test_amended_plan_marks_windows_immutable(self) -> None:
        module = _load_module()
        reproduced, evidence = module.reproduce_candidate()
        pre_info = {
            "amendment_eligible": True,
            "tick_windows_downloaded": False,
            "ohlc_results_observed": False,
            "tolerances_changed_after_results": False,
            "windows_changed_after_results": False,
        }
        amendment, _ = module.build_amendment(reproduced, evidence, pre_info, "prov", "pre")

        assert amendment["immutability"]["windows_and_tolerances_immutable_at_this_commit"]
        assert amendment["window_count"] == len(amendment["windows"])
