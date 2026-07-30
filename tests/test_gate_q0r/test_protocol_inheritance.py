from __future__ import annotations

import hashlib
import json
from pathlib import Path

from fx_smc_bot.research.quant_polarity import (
    CANDIDATES,
    FEATURES,
    HYPERPARAMETERS,
)

ROOT = Path(__file__).parents[2]
LOCK_PATH = ROOT / "results" / "gate_q0r" / "protocol_inheritance_lock.json"


def _load(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_inherited_protocol_semantics_are_exact() -> None:
    lock = _load(LOCK_PATH)
    assert lock["candidates"] == [candidate["candidate_id"] for candidate in CANDIDATES]
    assert lock["feature_count"] == len(FEATURES) == 18
    assert lock["hyperparameter_grid"] == {
        "C": [0.01, 0.1, 1.0],
        "combination_count": len(HYPERPARAMETERS),
        "l1_ratio": [0.0, 0.5, 1.0],
    }
    assert lock["decision_thresholds"] == {
        "ABSTAIN": "otherwise",
        "INVERSE": 0.55,
        "ORIGINAL": 0.55,
    }
    assert lock["purge_minutes"] == 2680
    assert lock["embargo_fx_trading_days"] == 5


def test_inherited_source_artifact_hashes_are_exact() -> None:
    lock = _load(LOCK_PATH)
    source_hashes = lock["source_artifact_sha256"]
    names = {
        "candidate_family_freeze": "candidate_family_freeze.json",
        "data_execution_contract": "data_execution_contract.json",
        "estimand_and_inference_freeze": "estimand_and_inference_freeze.json",
        "feature_and_label_freeze": "feature_and_label_freeze.json",
        "model_selection_freeze": "model_selection_freeze.json",
        "selection_and_replication_freeze": "selection_and_replication_freeze.json",
    }
    for key, filename in names.items():
        assert source_hashes[key] == _sha256(ROOT / "results" / "gate_q0" / filename)
