# Holdout Policy

## Data Split Structure

All validation campaigns split data into three disjoint segments:

| Segment | Default Range | Purpose |
|---------|--------------|---------|
| Training | 0% - 60% | Strategy development and initial evaluation |
| Validation | 60% - 80% | Walk-forward and stress testing |
| Holdout | 80% - 100% | Final locked evaluation, never touched during research |

## Embargo

An embargo of 10 bars (configurable) is inserted between each segment boundary to prevent autocorrelation leakage. Bars in the embargo gap are excluded from both adjacent segments.

## Configuration

```yaml
# configs/campaigns/holdout_policy.yaml
train_end_pct: 0.60
validation_end_pct: 0.80
embargo_bars: 10
```

Implemented via `DataSplitPolicy` in `research/frozen_config.py`.

## Rules

1. **Holdout is sacred**: No parameter tuning, model selection, or variant comparison may use holdout data
2. **One-shot evaluation**: Holdout evaluation happens exactly once per candidate in the `PAPER_TESTING` promotion stage
3. **Frozen configs only**: Only `FrozenCandidate` objects with validated hashes may access holdout data
4. **No peeking**: Walk-forward validation during the CANDIDATE stage uses only training+validation segments
5. **Embargo enforcement**: The `split_data()` function automatically inserts embargo gaps; manual slicing is not supported

## Purged Walk-Forward

Within the training/validation segment, `purged_walk_forward` creates anchored folds with an additional embargo between each fold's train and test windows. This is stricter than standard walk-forward.
