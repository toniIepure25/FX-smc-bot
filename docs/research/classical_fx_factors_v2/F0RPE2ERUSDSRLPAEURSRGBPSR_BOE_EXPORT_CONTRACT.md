# F0-RP-E2E-R-USDSR-LPA-EURSR-GBPSR BOE Export Contract

Contract ID: `BOE_IADB_MACHINE_READABLE_EXPORT_CONTRACT_V1`

This gate freezes the Bank of England IADB machine-readable export contract for
`IUDSOIA`, the daily Sterling Overnight Index Average series.

The active route precedence is:

1. CSV export from `_iadb-fromshowcolumns.asp`.
2. XML export from `_iadb-fromshowcolumns.asp` only when CSV remains inaccessible
   or structurally uncertifiable.
3. No HTML scraping fallback.

The CSV route requires `csv.x=yes`, bounded `Datefrom` and `Dateto`,
`SeriesCodes=IUDSOIA`, `UsingCodes=Y`, `CSVF=TN`, `VPD=N`, and `VFD=Y`.
`CSVF=TN` is frozen as `TABULAR_NO_TITLES`; it is not described as columnar.

The XML fallback route requires `CodeVer=new`, `xml.x=yes`, bounded `Datefrom`
and `Dateto`, `SeriesCodes=IUDSOIA`, `VPD=N`, and `VFD=Y`.

Only transparent headers are allowed: `Accept` and the descriptive research
client `User-Agent`. Browser impersonation, cookies, referer spoofing, session
tokens, CAPTCHA responses, and anti-bot circumvention remain prohibited.

Structural CSV access succeeded for all three bounded windows, so XML fallback
was not used.
