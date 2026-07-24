# Gate C5-A-DQR Provider Failure Analysis

Lowest-level observable failure:

`node fetch` receives HTTP `429` with body `{"error": "Too Many Requests"}`. The pinned package wraps this as `Unknown error`.

| Probe | Day | Side | Exit | HTTP | Node error |
| --- | --- | --- | ---: | ---: | --- |
| known_good_development_2019 | 2019-01-07 | bid | 1 | 429 | Unknown error |
| known_good_validation_2021 | 2021-01-06 | bid | 1 | 429 | Unknown error |
| failed_january_2020 | 2020-01-06 | bid | 1 | 429 | Unknown error |
