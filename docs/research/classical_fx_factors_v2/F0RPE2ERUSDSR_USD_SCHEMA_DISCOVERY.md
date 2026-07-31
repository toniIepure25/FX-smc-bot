# Gate F0-RP-E2E-R-USDSR USD Schema Discovery

Two successful, server-side bounded requests were sent to the frozen official New York Fed endpoint. The legacy request covered 2016-01-04 through 2016-01-08; the modern request covered 2016-03-01 through 2016-03-04. Both responses passed endpoint identity, content-type, UTF-8 JSON, request-bound and complete-response date checks before their raw payloads were persisted only in the external clean room.

The classification is `TWO_EXPLICITLY_VERSIONED_SCHEMAS`.

The legacy fingerprint is `da2935b38af012e67bf97d5900d44c64a9495b454262c698ae8827464cf7d00e`. Its `$.refRates` rows contain the common identity/date/rate/revision fields plus `intraDayHigh`, `intraDayLow`, `stdDeviation`, `targetRateFrom` and `targetRateTo`.

The modern fingerprint is `a002a5c557f22d51e9ac2171b981472589800ffe8a03d481629bd8844c165dff`. Its `$.refRates` rows replace the legacy distribution fields with `percentPercentile1`, `percentPercentile25`, `percentPercentile75` and `percentPercentile99`. The complete response contains both EFFR and OBFR type labels, so target fields are optional across the container. EFFR normalization therefore requires the exact official `type` value `EFFR`; event code 500 alone is not treated as row-level series proof.

No rate, percentile, volume, target, individual observation row or source payload fragment is committed. The shape inspector exposed zero numerical rows to the parser. The two accepted raw snapshots remain outside Git.
