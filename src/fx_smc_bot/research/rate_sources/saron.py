"""SIX/SNB selected 18:00 SARON fixing adapter."""

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


class Saron18Adapter:
    adapter_id = "SIX_SARON_1800_V1"
    currency = "CHF"
    series_id = "SRFXON3"
    parser_version = "SIX_SARON_1800_JSON_V1"
    publisher = "SIX Index AG"
    endpoint_role = "official_public_historical_export"
    schema_id = "six-saron-1800-official-v1"
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
            "fixingLabel",
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
                url="https://data.snb.ch/api/cube/zimoma/data/json/en",
                query_parameters={
                    "dimSel": self.series_id,
                    "fromDate": start.isoformat(),
                    "toDate": end.isoformat(),
                },
                authorization=authorization,
            ),
        )

    def parse_snapshot(self, snapshot: SourceSnapshot) -> tuple[RateVersion, ...]:
        self._validate_snapshot(snapshot)
        rows = strict_json_rows(
            snapshot, schema_id=self.schema_id, required_row_fields=self.required_fields
        )
        versions = tuple(
            version_from_row(
                snapshot,
                row,
                currency=self.currency,
                expected_series_id=self.series_id,
                publisher=self.publisher,
                parser_version=self.parser_version,
                day_count_convention="ACT_360",
                calendar_id="CHF_CURRENCY_BUSINESS_DAY",
                metadata_fields=("fixingLabel",),
            )
            for row in rows
        )
        if any(dict(version.source_metadata)["fixingLabel"] != "18:00" for version in versions):
            raise RateSourceError("INTRADAY_SARON_FIXING_PROHIBITED")
        return reject_duplicate_versions(versions)

    def certify_version(self, version: RateVersion) -> RateCertification:
        result = certify_common(
            version,
            adapter_id=self.adapter_id,
            currency=self.currency,
            series_ids=frozenset({self.series_id}),
            publisher=self.publisher,
            parser_version=self.parser_version,
            day_count_convention="ACT_360",
            calendar_id="CHF_CURRENCY_BUSINESS_DAY",
            publication_zone="Europe/Zurich",
            endpoint_roles=frozenset({self.endpoint_role}),
        )
        local = version.strategy_availability_timestamp.astimezone(ZoneInfo("Europe/Zurich"))
        reasons = []
        if local.date() <= version.observation_date or (local.hour, local.minute) < (18, 0):
            reasons.append("SARON_PUBLIC_REDISTRIBUTION_ENVELOPE_NOT_CLOSED")
        return combine_certification(result, reasons)

    def _validate_snapshot(self, snapshot: SourceSnapshot) -> None:
        if (
            snapshot.request.adapter_id != self.adapter_id
            or snapshot.request.series_id != self.series_id
        ):
            raise RateSourceError("SNAPSHOT_REQUEST_IDENTITY_MISMATCH")


class Saron18AdapterV2(Saron18Adapter):
    """Future-baseline adapter restricted to the selected 18:00 SARON fixing."""

    adapter_id = "SIX_SARON_1800_V2"
    parser_version = "SIX_SARON_1800_JSON_V2"
    schema_id = "SNB_CUBE_JSON_V2"
    publisher = "Swiss National Bank / SIX Index AG"
    endpoint_declarations = (
        OfficialNumericalEndpoint(
            allowlist_identity="F0RPE2ER_OFFICIAL_SOURCE_ALLOWLIST_V1",
            adapter_id=adapter_id,
            currency=Saron18Adapter.currency,
            series_id=Saron18Adapter.series_id,
            publisher=publisher,
            url="https://data.snb.ch/api/cube/zimoma/data/json/en",
            start_parameter="fromDate",
            end_parameter="toDate",
            series_parameter="dimSel",
            series_parameter_value="SRFXON3",
            response_format="JSON",
            accept_media_type="application/json",
            format_parameter=None,
            format_parameter_value=None,
            series_path_token=None,
            format_path_token="/json/",
            schema_id=schema_id,
            required_fields=tuple(sorted(Saron18Adapter.required_fields)),
            schema_fingerprint=schema_fingerprint(
                schema_id, Saron18Adapter.required_fields
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
                    "dimSel": self.series_id,
                    "fromDate": start.isoformat(),
                    "toDate": end.isoformat(),
                },
                authorization=authorization,
            ),
        )

    def parse_snapshot(self, snapshot: SourceSnapshot) -> tuple[RateVersion, ...]:
        validate_v2_snapshot(
            snapshot, adapter_id=self.adapter_id, declarations=self.endpoint_declarations
        )
        return super().parse_snapshot(snapshot)
