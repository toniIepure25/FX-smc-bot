# Gate F0-RP-E2E Provenance Inheritance

## Status

`PASS`

Gate F0-RP-E2E preserves the original Gate F0 decision
`BLOCKED_BY_RATE_DATA_PROVENANCE` and the Gate F0-RP decision
`F0RP_RATE_PROVENANCE_RECONCILED_EMPIRICAL_EXECUTION_BLOCKED` without
reclassification or mutation.

The outcome-blind amendment remains `F0_RATE_PROVENANCE_AMENDMENT_V1`, with
amendment hash
`e1a2245542cb74f1eb48bbdba01e9bcd9689662b13d8069602297c97705e904b`
and pre-data-access commit `62ee708891b8ee056bf8052f74eece2cb71bba49`.
Its selected route remains `OUTCOME_BLIND_NZD_EXCLUSION`. NZD and NZDUSD are
excluded and cannot be requested by this gate.

All minimum F0 and F0-RP decision and provenance artifacts were read and
hashed using UTF-8 text with LF-normalized line endings. The hashes are pinned
in `results/gate_f0rpe2e/provenance_inheritance.json`. The worktree was clean
at the gate boundary, no pre-amendment observations were accessed, and no
historical artifact was changed.
