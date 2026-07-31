# Gate F0-RP-E2E-R Documentation And Data Boundary

Boundary `F0RPE2ER_DOCUMENTATION_DATA_BOUNDARY_V1` separates metadata from
numerical observations. Class A may establish methodology, schemas, release and
revision rules, calendars, and series identities, but cannot feed numerical
values to the program. Search snippets, dashboards, observation tables, latest
files, and unbounded exports are prohibited.

Class B permits only allowlisted official machine-readable requests containing
explicit series, currency, format, start date, and end date no later than
2022-12-31. Every complete response must pass the atomic response-date firewall.
The allowlist was frozen before numerical network access.
