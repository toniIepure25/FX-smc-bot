# A0 Trial Accounting

Gate: `A0_INTRADAY_ALPHA_DISCOVERY_FACTORY_V1`

Registry: `A0_TRIAL_REGISTRY_V1`

Global candidate-equivalent trial budget: `1200`

Every attempted configuration counts before its outcome is computed. This
includes parameter settings, feature subsets, target horizons, model classes,
random seeds, ensembles, thresholds and position-sizing variants.

Trial statuses:

```text
REGISTERED
RUNNING
COMPLETED
FAILED_TECHNICAL
INVALID_PROTOCOL
```

No failed, losing, invalid or technically unsuccessful trial may be deleted from
the registry.

Current registry state:

```text
registered_trials:
0

reason:
market-data acquisition has not begun because FX_A0_DATA_ROOT is not configured
```
