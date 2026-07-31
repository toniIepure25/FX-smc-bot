# Gate Q0-R Final Decision

## Decision

`Q0R_NO_CANDIDATE_SURVIVED_INDEPENDENT_REPLICATION`

The frozen development rules selected no candidate. The replication shortlist
was committed empty before any replication data access, so replication
acquisition, outcomes, Tier A/B adjudication, and future-candidate freeze were
not run.

## Integrity

The original Q.0 integrity failure remains valid and unchanged.

The 2023-2025 interval is not treated as an untouched confirmatory holdout. It
remains permanently classified
`QUARANTINED_FROM_CONFIRMATORY_USE_DUE_TO_Q0_STORAGE_ENUMERATION`.

Q.0-R used a new clean-room root and only prespecified 2015-2019 development
data. The conditional 2020-2022 replication interval was not accessed because
the shortlist was empty. No old Q.0 market file, checkpoint, or provider payload
was reused.

The replacement confirmatory dataset is all eligible observations beginning on
the first complete FX trading day strictly after a final candidate-freeze
commit. No such date exists in this gate because no candidate was frozen.

## Development Result

The clean-room development dataset certified all 240 planned pair-months, with
7,455,419 M1 rows and 1,494,623 M5 rows. The selected elastic-net
hyperparameters were `C=0.01` and `l1_ratio=0.0`; purge was 2,680 minutes and
embargo was five FX trading days.

| Candidate | Trades | Mean net R | PF | 1.5x cost mean R |
| --- | ---: | ---: | ---: | ---: |
| `Q0_INV_SWEEP_V1` | 364 | -0.321805 | 0.297522 | -0.356640 |
| `Q0_INV_ACCEPTANCE_V1` | 6,932 | -0.762445 | 0.107293 | -0.858735 |
| `Q0_INV_LONDON_OR_V1` | 930 | -0.410300 | 0.160778 | -0.471346 |
| `Q0_INV_NEWYORK_OR_V1` | 1,488 | -0.421101 | 0.233314 | -0.473285 |
| `Q0_META_POLARITY_ELASTIC_NET_V1` | 6 | -0.121867 | 0.077613 | -0.133150 |

All deterministic candidates were negative in every development year and on
every instrument. The meta candidate had only six trades, one positive
instrument mean, and no year with 20 trades. Matched-random alpha was negative
for every candidate. White Reality Check was 0.9898, Hansen SPA was 1.0, and PBO
was 1.0. No result supports positive alpha.

The very small Romano-Wolf values for four deterministic candidates accompany
negative candidate effects; they are evidence of reliably poor relative
performance, not positive evidence. The meta-model HAC estimate is numerically
unstable because it uses only five daily observations and is not interpreted as
evidence.

## Quality And Scope

The final suite passed with 935 tests and 91 warnings. Targeted Ruff and mypy
passed, the branch introduced zero new Ruff and zero new mypy findings against
`origin/main`, the Node wrapper tests passed 2/2, and `git diff --check` passed.

Any selected candidate would remain unconfirmed until genuinely future
prospective data satisfy both the frozen minimum of 100 accepted trades and 90
calendar days. No candidate was selected here.

No result authorizes live-capital deployment.
