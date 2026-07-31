# Gate F0-RP Rate Provenance Audit

## Scope

This audit used official central-bank and benchmark-administrator metadata,
methodology, schedule, and announcement pages only. It did not access a
numerical market or rate observation file and sent no provider request.

The strategy availability rule remains the later of original publication and
effective timestamps. Revisions are never backfilled. An observation without a
proven official availability rule is missing, and interpolation is forbidden.

## Registry Results

| Currency | Series | Classification | Conservative strategy availability |
| --- | --- | --- | --- |
| USD | EFFR | `CERTIFIABLE_WITH_CONSERVATIVE_OFFICIAL_AVAILABILITY_ENVELOPE` | Following NY Fed business day after the official revision window |
| EUR | EONIA to ESTR | `POINT_IN_TIME_CERTIFIABLE` | EONIA after 19:00 CET on T; ESTR after 09:00 CET on T+1 TARGET2 day |
| GBP | IUDSOIA / SONIA | `CERTIFIABLE_WITH_CONSERVATIVE_OFFICIAL_AVAILABILITY_ENVELOPE` | T+1 London business day at 12:00 |
| AUD | RBA cash rate / AONIA | `CERTIFIABLE_WITH_CONSERVATIVE_OFFICIAL_AVAILABILITY_ENVELOPE` | Following RITS business day at 16:00 Sydney time |
| NZD | B2 overnight interbank cash rate | `NOT_POINT_IN_TIME_CERTIFIABLE` | None; publication timestamps or lags must not be inferred |
| JPY | `FM01'STRDCLUCON` | `CERTIFIABLE_WITH_CONSERVATIVE_OFFICIAL_AVAILABILITY_ENVELOPE` | End of T+1 BOJ publication day, final result only |
| CAD | V39079 | `POINT_IN_TIME_CERTIFIABLE` | Later of official decision release and official effective time |
| CHF | SRFXON3 | `CERTIFIABLE_WITH_CONSERVATIVE_OFFICIAL_AVAILABILITY_ENVELOPE` | T+1 at 18:00 Zurich for public historical redistribution |

The machine-readable audit records economic meaning, observation date,
publication and revision rules, timezone, calendar, day count, transition,
missing-value policy, availability envelope, and official evidence URLs for
each series.

## NZD Route A Assessment

The official RBNZ record supports 09:00 scheduled announcements in 2010-2018
and a transition to 14:00 Wednesday announcements with next-working-day market
implementation from 2019. The official decision archive also records the OCR
dates, levels, and linked releases.

The unscheduled OCR reduction dated 16 March 2020 is the decisive gap. The
official archived release proves the decision date, new rate, and effective
date, but the available RBNZ release metadata does not preserve an original
publication time and supplies no deterministic rule for that exceptional
announcement. Assigning the scheduled 14:00 time or an externally reported time
would be inference.

Therefore the full 2010-2022 OCR event registry required by Route A is not
certifiable. Route A is rejected without consulting portfolio outcomes, and
Route B must exclude NZD and NZDUSD before any observation access.

## Official Evidence

- NY Fed: <https://www.newyorkfed.org/markets/reference-rates/effr>
- ECB: <https://data.ecb.europa.eu/data/datasets/EON/data-information>
- Bank of England: <https://www.bankofengland.co.uk/markets/sonia-benchmark/sonia-key-features-and-policies>
- RBA: <https://www.rba.gov.au/mkt-operations/resources/cash-rate-methodology/cash-rate-procedures-manual.html>
- RBNZ B2: <https://www.rbnz.govt.nz/statistics/series/exchange-and-interest-rates/wholesale-interest-rates>
- RBNZ OCR archive: <https://www.rbnz.govt.nz/monetary-policy/monetary-policy-decisions>
- BOJ: <https://www.boj.or.jp/en/statistics/market/short/mutan/index.htm>
- Bank of Canada: <https://www.bankofcanada.ca/rates/indicators/key-variables/policy-instrument/>
- SIX: <https://www.six-group.com/en/market-data/indices/switzerland/saron.html>
