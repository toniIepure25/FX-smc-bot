"""Reserve Bank of Australia official cash-rate adapter."""

from __future__ import annotations

from datetime import date
from zoneinfo import ZoneInfo

from fx_smc_bot.research.rate_sources.base import (
    OfficialNumericalEndpoint,
    OfficialRateRequest,
    RateAccessAuthorization,
    RateCertification,
    RateSourceError,
    RateVersion,
    SourceSnapshot,
    certify_common,
    combine_certification,
    make_request,
    make_v2_request,
    reject_duplicate_versions,
    schema_fingerprint,
    strict_json_rows,
    validate_v2_snapshot,
    version_from_row,
)


class RbaCashRateAdapter:
    adapter_id = "RBA_CASH_RATE_V1"
    currency = "AUD"
    series_id = "RBA_CASH_RATE"
    parser_version = "RBA_CASH_RATE_JSON_V1"
    publisher = "Reserve Bank of Australia"
    endpoint_role = "official_cash_rate_export"
    schema_id = "rba-cash-rate-official-v1"
    required_fields = frozenset(
        {
            "currency",
            "seriesId",
            "observationDate",
            "value",
            "publicationTimestamp",
            "effectiveTimestamp",
            "sourceDocumentId",
            "revisionIdentifier",
            "revisionStatus",
            "methodologyRegime",
        }
    )

    def build_requests(
        self, start: date, end: date, authorization: RateAccessAuthorization
    ) -> tuple[OfficialRateRequest, ...]:
        return (
            make_request(
                adapter_id=self.adapter_id,
                currency=self.currency,
                series_id=self.series_id,
                publisher=self.publisher,
                endpoint_role=self.endpoint_role,
                start=start,
                end=end,
                url="https://www.rba.gov.au/statistics/cash-rate/cash-rate.json",
                query_parameters={"end-date": end.isoformat(), "start-date": start.isoformat()},
                authorization=authorization,
            ),
        )

    def parse_snapshot(self, snapshot: SourceSnapshot) -> tuple[RateVersion, ...]:
        self._validate_snapshot(snapshot)
        rows = strict_json_rows(
            snapshot, schema_id=self.schema_id, required_row_fields=self.required_fields
        )
        return reject_duplicate_versions(
            tuple(
                version_from_row(
                    snapshot,
                    row,
                    currency=self.currency,
                    expected_series_id=self.series_id,
                    publisher=self.publisher,
                    parser_version=self.parser_version,
                    day_count_convention="ACT_365_FIXED",
                    calendar_id="RITS_BUSINESS_DAY",
                    metadata_fields=("methodologyRegime",),
                )
                for row in rows
            )
        )

    def certify_version(self, version: RateVersion) -> RateCertification:
        result = certify_common(
            version,
            adapter_id=self.adapter_id,
            currency=self.currency,
            series_ids=frozenset({self.series_id}),
            publisher=self.publisher,
            parser_version=self.parser_version,
            day_count_convention="ACT_365_FIXED",
            calendar_id="RITS_BUSINESS_DAY",
            publication_zone="Australia/Sydney",
            endpoint_roles=frozenset({self.endpoint_role}),
        )
        local = version.strategy_availability_timestamp.astimezone(ZoneInfo("Australia/Sydney"))
        reasons = []
        if local.date() <= version.observation_date or (local.hour, local.minute) < (16, 0):
            reasons.append("RBA_BEFORE_CONSERVATIVE_REVISION_ENVELOPE")
        return combine_certification(result, reasons)

    def _validate_snapshot(self, snapshot: SourceSnapshot) -> None:
        if (
            snapshot.request.adapter_id != self.adapter_id
            or snapshot.request.series_id != self.series_id
        ):
            raise RateSourceError("SNAPSHOT_REQUEST_IDENTITY_MISMATCH")


class RbaCashRateAdapterV2(RbaCashRateAdapter):
    """Future-baseline RBA cash-rate adapter with bounded query identity."""

    adapter_id = "RBA_CASH_RATE_V2"
    parser_version = "RBA_CASH_RATE_JSON_V2"
    schema_id = "RBA_CASH_RATE_JSON_V2"
    endpoint_declarations = (
        OfficialNumericalEndpoint(
            allowlist_identity="F0RPE2ER_OFFICIAL_SOURCE_ALLOWLIST_V1",
            adapter_id=adapter_id,
            currency=RbaCashRateAdapter.currency,
            series_id=RbaCashRateAdapter.series_id,
            publisher=RbaCashRateAdapter.publisher,
            url="https://www.rba.gov.au/statistics/cash-rate/cash-rate.json",
            start_parameter="start-date",
            end_parameter="end-date",
            series_parameter="FIXED_ENDPOINT_SERIES",
            series_parameter_value="RBA_CASH_RATE",
            response_format="JSON",
            accept_media_type="application/json",
            format_parameter=None,
            format_parameter_value=None,
            series_path_token=None,
            format_path_token=".json",
            schema_id=schema_id,
            required_fields=tuple(sorted(RbaCashRateAdapter.required_fields)),
            schema_fingerprint=schema_fingerprint(
                schema_id, RbaCashRateAdapter.required_fields
            ),
            publication_timestamp_field="publicationTimestamp",
            effective_timestamp_field="effectiveTimestamp",
        ),
    )

    def build_requests(
        self, start: date, end: date, authorization: RateAccessAuthorization
    ) -> tuple[OfficialRateRequest, ...]:
        return (
            make_v2_request(
                declaration=self.endpoint_declarations[0],
                endpoint_role=self.endpoint_role,
                start=start,
                end=end,
                query_parameters={
                    "end-date": end.isoformat(),
                    "start-date": start.isoformat(),
                },
                authorization=authorization,
            ),
        )

    def parse_snapshot(self, snapshot: SourceSnapshot) -> tuple[RateVersion, ...]:
        validate_v2_snapshot(
            snapshot, adapter_id=self.adapter_id, declarations=self.endpoint_declarations
        )
        return super().parse_snapshot(snapshot)
