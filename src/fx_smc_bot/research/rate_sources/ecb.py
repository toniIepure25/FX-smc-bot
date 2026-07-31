"""ECB EONIA-to-euro-short-term-rate transition adapter."""

from __future__ import annotations

from datetime import date

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

EONIA_END = date(2019, 9, 30)
ESTR_START = date(2019, 10, 1)


class EcbEoniaEstrAdapter:
    adapter_id = "ECB_EONIA_ESTR_V1"
    currency = "EUR"
    series_id = "EONIA_TO_ESTR"
    parser_version = "ECB_EONIA_ESTR_JSON_V1"
    publisher = "European Central Bank"
    endpoint_role = "official_ecb_data_export"
    schema_id = "ecb-overnight-rate-official-v1"
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
            "publicationType",
            "calculationMethod",
        }
    )

    def build_requests(
        self, start: date, end: date, authorization: RateAccessAuthorization
    ) -> tuple[OfficialRateRequest, ...]:
        if start > end:
            raise RateSourceError("REQUEST_INTERVAL_INVALID")
        requests: list[OfficialRateRequest] = []
        if start <= EONIA_END:
            requests.append(self._request("EONIA", start, min(end, EONIA_END), authorization))
        if end >= ESTR_START:
            requests.append(self._request("ESTR", max(start, ESTR_START), end, authorization))
        return tuple(requests)

    def parse_snapshot(self, snapshot: SourceSnapshot) -> tuple[RateVersion, ...]:
        source_series = snapshot.request.series_id
        if snapshot.request.adapter_id != self.adapter_id or source_series not in {"EONIA", "ESTR"}:
            raise RateSourceError("SNAPSHOT_REQUEST_IDENTITY_MISMATCH")
        rows = strict_json_rows(
            snapshot, schema_id=self.schema_id, required_row_fields=self.required_fields
        )
        versions = tuple(
            version_from_row(
                snapshot,
                row,
                currency=self.currency,
                expected_series_id=source_series,
                publisher=self.publisher,
                parser_version=self.parser_version,
                day_count_convention="ACT_360",
                calendar_id="TARGET2",
                metadata_fields=("publicationType", "calculationMethod"),
            )
            for row in rows
        )
        for version in versions:
            if (version.series_id == "EONIA") != (version.observation_date <= EONIA_END):
                raise RateSourceError("EONIA_ESTR_TRANSITION_VIOLATION")
        return reject_duplicate_versions(versions)

    def certify_version(self, version: RateVersion) -> RateCertification:
        result = certify_common(
            version,
            adapter_id=self.adapter_id,
            currency=self.currency,
            series_ids=frozenset({"EONIA", "ESTR"}),
            publisher=self.publisher,
            parser_version=self.parser_version,
            day_count_convention="ACT_360",
            calendar_id="TARGET2",
            publication_zone="Europe/Brussels",
            endpoint_roles=frozenset({self.endpoint_role}),
        )
        reasons = []
        if version.series_id == "EONIA" and version.observation_date > EONIA_END:
            reasons.append("EONIA_AFTER_FROZEN_TRANSITION")
        if version.series_id == "ESTR" and version.observation_date < ESTR_START:
            reasons.append("ESTR_BEFORE_FROZEN_TRANSITION")
        if (
            version.series_id == "ESTR"
            and version.publication_timestamp.date() <= version.observation_date
        ):
            reasons.append("ESTR_PUBLICATION_MUST_FOLLOW_OBSERVATION_DATE")
        return combine_certification(result, reasons)

    def _request(
        self,
        source_series: str,
        start: date,
        end: date,
        authorization: RateAccessAuthorization,
    ) -> OfficialRateRequest:
        dataset = "EON" if source_series == "EONIA" else "EST"
        return make_request(
            adapter_id=self.adapter_id,
            currency=self.currency,
            series_id=source_series,
            publisher=self.publisher,
            endpoint_role=self.endpoint_role,
            start=start,
            end=end,
            url=f"https://data-api.ecb.europa.eu/service/data/{dataset}/B.EU000A2X2A25.WT",
            query_parameters={
                "detail": "full",
                "endPeriod": end.isoformat(),
                "format": "jsondata",
                "startPeriod": start.isoformat(),
            },
            authorization=authorization,
        )


class EcbEoniaEstrAdapterV2(EcbEoniaEstrAdapter):
    """Future-baseline EUR transition adapter with two disjoint declarations."""

    adapter_id = "ECB_EONIA_ESTR_V2"
    parser_version = "ECB_EONIA_ESTR_JSON_V2"
    schema_id = "ECB_SDMX_JSONDATA_V2"
    endpoint_declarations = tuple(
        OfficialNumericalEndpoint(
            allowlist_identity="F0RPE2ER_OFFICIAL_SOURCE_ALLOWLIST_V1",
            adapter_id="ECB_EONIA_ESTR_V2",
            currency=EcbEoniaEstrAdapter.currency,
            series_id=source_series,
            publisher=EcbEoniaEstrAdapter.publisher,
            url=f"https://data-api.ecb.europa.eu/service/data/{dataset}/B.EU000A2X2A25.WT",
            start_parameter="startPeriod",
            end_parameter="endPeriod",
            series_parameter="PATH_SERIES_KEY",
            series_parameter_value=source_series,
            response_format="JSONDATA",
            accept_media_type="application/json",
            format_parameter="format",
            format_parameter_value="jsondata",
            series_path_token=f"/data/{dataset}/B.EU000A2X2A25.WT",
            format_path_token=None,
            schema_id="ECB_SDMX_JSONDATA_V2",
            required_fields=tuple(sorted(EcbEoniaEstrAdapter.required_fields)),
            schema_fingerprint=schema_fingerprint(
                "ECB_SDMX_JSONDATA_V2", EcbEoniaEstrAdapter.required_fields
            ),
            publication_timestamp_field="publicationTimestamp",
            effective_timestamp_field="effectiveTimestamp",
        )
        for source_series, dataset in (("EONIA", "EON"), ("ESTR", "EST"))
    )

    def _request(
        self,
        source_series: str,
        start: date,
        end: date,
        authorization: RateAccessAuthorization,
    ) -> OfficialRateRequest:
        declaration = next(
            item for item in self.endpoint_declarations if item.series_id == source_series
        )
        return make_v2_request(
            declaration=declaration,
            endpoint_role=self.endpoint_role,
            start=start,
            end=end,
            query_parameters={
                "detail": "full",
                "endPeriod": end.isoformat(),
                "format": "jsondata",
                "startPeriod": start.isoformat(),
            },
            authorization=authorization,
        )

    def parse_snapshot(self, snapshot: SourceSnapshot) -> tuple[RateVersion, ...]:
        validate_v2_snapshot(
            snapshot, adapter_id=self.adapter_id, declarations=self.endpoint_declarations
        )
        return super().parse_snapshot(snapshot)
