"""Synthetic-only A0R2 trial event and shortlist adjudication."""

from __future__ import annotations

from dataclasses import dataclass

VALID_TRIAL_STATES = {
    "REGISTERED",
    "COMPLETED",
    "FAILED_TECHNICAL",
    "INVALID_PROTOCOL_DATA_CAPABILITY",
}


@dataclass(frozen=True, slots=True)
class TrialResult:
    trial_id: str
    status: str
    net_score: float = 0.0
    adjusted_p_value: float = 1.0


def transition_trial_status(current: str, new: str) -> str:
    if current not in VALID_TRIAL_STATES or new not in VALID_TRIAL_STATES:
        raise ValueError("A0R2_INVALID_TRIAL_STATE")
    if current in {"COMPLETED", "FAILED_TECHNICAL", "INVALID_PROTOCOL_DATA_CAPABILITY"}:
        return current
    return new


def adjudicate_shortlist(results: list[TrialResult], alpha: float) -> list[str]:
    return [
        result.trial_id
        for result in results
        if result.status == "COMPLETED"
        and result.net_score > 0.0
        and result.adjusted_p_value <= alpha
    ]
