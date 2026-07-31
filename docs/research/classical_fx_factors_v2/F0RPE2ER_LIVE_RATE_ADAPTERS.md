# F0-RP-E2E-R Live Rate Adapters

The first required live request used the allowlisted New York Fed endpoint and the bounded interval 2016-01-04 through 2016-01-08. The HTTP response reached the firewall, but its schema did not match `NY_FED_RATES_SEARCH_JSON_V2`. The response was rejected atomically before persistence. No other adapter and no market source was accessed under the fail-fast rule.
