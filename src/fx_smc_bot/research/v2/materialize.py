"""Deterministic V2 trial materialization.

Admitted compile results are frozen into immutable trial records. Re-running
materialization with the same inputs produces byte-identical logical configurations and
identical hashes (a clean-room reproduction test asserts this). Every trial carries the
full hash chain required to reproduce it: configuration, semantic spec, data capability,
execution contract and statistical protocol, plus repository-relative provenance.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from fx_smc_bot.research.v2.capabilities import capability_matrix_payload
from fx_smc_bot.research.v2.compiler import CompileResult
from fx_smc_bot.research.v2.protocol import protocol_hash
from fx_smc_bot.research.v2.spec import StrategySpec

CONFIG_PATH = "configs/research/fx_intraday_alpha_search_v2.yaml"


def _hash(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _semantic_spec_hash(spec: StrategySpec) -> str:
    skeleton = {
        "family_id": spec.family_id,
        "feature_kind": spec.feature.kind.value,
        "required_capabilities": sorted(spec.required_capabilities),
        "model_class": spec.model.model_class.value if spec.model else "none",
        "model_target": spec.model.target.value if (spec.model and spec.model.target) else None,
    }
    return _hash(skeleton)


def _execution_contract_hash(spec: StrategySpec) -> str:
    return _hash(spec.execution.as_dict())


def materialize(
    admitted: list[CompileResult],
    *,
    git_sha: str = "",
) -> list[dict[str, Any]]:
    """Return immutable, deterministically-ordered materialized trial records."""

    data_capability_hash = _hash(capability_matrix_payload())
    stat_hash = protocol_hash()
    ordered = sorted(admitted, key=lambda r: (r.family_id, r.instrument, r.spec_hash))
    trials: list[dict[str, Any]] = []
    for seq, result in enumerate(ordered):
        spec = result.spec
        trial_id = f"V2-{seq:04d}"
        record = {
            "trial_id": trial_id,
            "family_id": spec.family_id,
            "instrument": spec.instrument,
            "terminal_state": result.terminal_state,
            "full_configuration": result.canonical_config,
            "configuration_hash": result.spec_hash,
            "semantic_spec_hash": _semantic_spec_hash(spec),
            "data_capability_hash": data_capability_hash,
            "execution_contract_hash": _execution_contract_hash(spec),
            "statistical_protocol_hash": stat_hash,
            "provenance": {
                "config_path": CONFIG_PATH,
                "capability_matrix_artifact": "results/gate_a0r4/data_capability_matrix.json",
                "statistical_protocol_artifact": "results/gate_a0r4/statistical_protocol.json",
                "survivor_predicate_artifact": "results/gate_a0r4/survivor_predicate.json",
                "git_sha": git_sha,
            },
        }
        trials.append(record)
    return trials


def rejected_payload(rejected: list[CompileResult]) -> list[dict[str, Any]]:
    ordered = sorted(rejected, key=lambda r: (r.family_id, r.instrument, r.spec_hash))
    return [
        {
            "family_id": r.family_id,
            "instrument": r.instrument,
            "terminal_state": r.terminal_state,
            "configuration_hash": r.spec_hash,
            "reasons": list(r.reasons),
            "semantic_spec_hash": _semantic_spec_hash(r.spec),
        }
        for r in ordered
    ]


def materialization_digest(trials: list[dict[str, Any]]) -> str:
    """A single digest over the ordered materialized universe (for reproduction tests)."""

    return _hash([t["trial_id"] + ":" + t["configuration_hash"] for t in trials])
