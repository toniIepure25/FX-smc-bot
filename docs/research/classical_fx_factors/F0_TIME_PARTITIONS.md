# Gate F.0 Time Partitions

Program `FX_CLASSICAL_RISK_PREMIA_V1` freezes the following mutually exclusive
calendar partitions:

| Partition | Inclusive interval | Permitted use |
|---|---|---|
| Warm-up only | 2010-01-01 to 2010-12-31 | Indicator initialization only |
| Development | 2011-01-01 to 2016-12-31 | Candidate eligibility |
| Internal validation | 2017-01-01 to 2019-12-31 | Frozen-shortlist adjudication |
| Independent replication | 2020-01-01 to 2022-12-31 | One-time frozen-shortlist replication |
| Quarantined | 2023-01-01 to 2025-12-31 | `QUARANTINED_FROM_CONFIRMATORY_USE` |

The quarantined partition must not be accessed, enumerated, requested from a
provider, represented as an untouched holdout, or used for any inference.

The future confirmatory interval begins on the first complete FX trading day
strictly after the final portfolio-freeze commit. Gate F.0 must not collect,
enumerate, or evaluate that future interval.

Partition access is sequential: development certification precedes development
outcomes; the validation shortlist is committed before validation access; the
replication shortlist is committed before replication access. If no candidate
advances, later partitions are not acquired.

The lineage is `FX_CLASSICAL_FACTOR_DISCOVERY_LINEAGE_V1`; the prior SMC and
quant-polarity lineage seals remain closed. This freeze contains no result.
