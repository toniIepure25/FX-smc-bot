# Gate F.0 Clean-Room Architecture

Applies to program `FX_CLASSICAL_RISK_PREMIA_V1`, lineage
`FX_CLASSICAL_FACTOR_DISCOVERY_LINEAGE_V1`. The prior SMC and quant-polarity
lineage seals remain closed.

## Root

All F.0 market and rate data must be contained by `FX_F0_DATA_ROOT`. When the
environment variable is unset, resolve exactly:

```text
<repository-parent>/FX-smc-bot-local-data/f0_classical_factors_v1
```

The resolved root must be outside the repository, newly created for F.0,
initially empty, and neither equal to nor a parent or child of a prior data
root. This separation must be established without inspecting prior roots.
Symlink, junction, reparse-point, and path-normalization escapes are forbidden.
Only the exact resolved root may be created.

## Capability-restricted I/O

Every filesystem or provider operation requires an immutable authorization
object containing:

- clean-room root;
- authorized instruments and currencies;
- authorized date interval and partition set;
- authorized provider;
- authorized operation.

Authorization and canonical-path checks occur before filesystem enumeration,
file opening, or provider requests. Recursive wildcards, broad repository or
parent searches, `os.walk`, `Path.rglob`, and `glob("**/*")` are forbidden.

Raw payloads, canonical bars, row-level rates, factors, positions, orders,
returns, transactions, costs, credentials, and absolute clean-room paths must
never be committed. Only compact schemas, hashes, counts, certifications, and
aggregate research artifacts are Git-eligible.

Failure of root isolation or capability enforcement requires
`BLOCKED_BY_NEW_LINEAGE_BOUNDARY` or the more specific applicable data-safety
decision. This document records architecture only, not a clean-room result.
