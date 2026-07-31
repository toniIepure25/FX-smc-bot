from datetime import UTC, datetime, timedelta

import numpy as np

from fx_smc_bot.research.quant_polarity_model import (
    LabeledSignal,
    PolarityAction,
    actions_from_probabilities,
    annual_purged_forward_folds,
    construct_label,
)


def _signal(year: int, day: int, label_hours: int = 2) -> LabeledSignal:
    decision = datetime(year, 1, day, 12, tzinfo=UTC)
    return LabeledSignal(
        decision,
        decision + timedelta(hours=label_hours),
        "AUDUSD",
        {},
        PolarityAction.ABSTAIN,
    )


def test_label_contract_is_exact() -> None:
    assert construct_label(0.2, -0.2) is PolarityAction.ORIGINAL
    assert construct_label(-0.2, 0.2) is PolarityAction.INVERSE
    assert construct_label(0.0, 0.0) is PolarityAction.ABSTAIN
    assert construct_label(0.2, 0.2) is PolarityAction.ABSTAIN


def test_outer_folds_are_strictly_forward_purged_and_embargoed() -> None:
    signals = [_signal(2015, day) for day in range(1, 20)]
    signals.extend(_signal(2016, day) for day in range(1, 20))
    folds = annual_purged_forward_folds(signals, purge_dependency=timedelta(hours=44))
    assert len(folds) == 1
    fold = folds[0]
    assert fold.fold_id == "OUTER_2016"
    assert fold.embargo_days == 5
    assert fold.train_latest_label_end < fold.purge_cutoff
    assert fold.train_latest_decision < fold.test_earliest_decision


def test_fixed_decision_thresholds() -> None:
    classes = ["ABSTAIN", "INVERSE", "ORIGINAL"]
    probabilities = np.asarray(
        [[0.1, 0.2, 0.7], [0.1, 0.6, 0.3], [0.4, 0.3, 0.3]], dtype=float
    )
    assert actions_from_probabilities(classes, probabilities) == (
        PolarityAction.ORIGINAL,
        PolarityAction.INVERSE,
        PolarityAction.ABSTAIN,
    )
