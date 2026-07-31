"""Federal Reserve Bank of New York EFFR adapter."""

from __future__ import annotations

from datetime import date
from zoneinfo import ZoneInfo

from fx_smc_bot.research.rate_sources.base import (
    OfficialRateRequest,
    RateAccessAuthorization,
    RateCertification,
    RateSourceError,
    RateVersion,
    SourceSnapshot,
    certify_common,
    combine_certification,
    make_request,
    reject_duplicate_versions,
    strict_json_rows,
    version_from_row,
)


class NewYorkFedEffrAdapter:
    adapter_id = "NY_FED_EFFR_V1"
    currency = "USD"
    series_id = "EFFR"
    parser_version = "NY_FED_EFFR_JSON_V1"
    publisher = "Federal Reserve Bank of New York"
    schema_id = "ny-fed-effr-official-v1"
    endpoint_role = "official_reference_rate_export"
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
            "footnotes",
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
                url="https://markets.newyorkfed.org/api/rates/all/search.json",
                query_parameters={
                    "endDate": end.isoformat(),
                    "eventCodes": "500",
                    "format": "json",
                    "startDate": start.isoformat(),
                    "type": "rate",
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
                calendar_id="NEW_YORK_FED_BUSINESS_DAY",
                metadata_fields=("footnotes",),
            )
            for row in rows
        )
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
            calendar_id="NEW_YORK_FED_BUSINESS_DAY",
            publication_zone="America/New_York",
            endpoint_roles=frozenset({self.endpoint_role}),
        )
        local = version.publication_timestamp.astimezone(ZoneInfo("America/New_York"))
        reasons = []
        if local.date() <= version.observation_date:
            reasons.append("EFFR_PUBLICATION_MUST_FOLLOW_OBSERVATION_DATE")
        if version.revision_status in {"REVISED", "CORRECTED"} and (
            local.hour,
            local.minute,
        ) < (14, 30):
            reasons.append("EFFR_REVISION_BEFORE_OFFICIAL_WINDOW")
        return combine_certification(result, reasons)

    def _validate_snapshot(self, snapshot: SourceSnapshot) -> None:
        request = snapshot.request
        if request.adapter_id != self.adapter_id or request.series_id != self.series_id:
            raise RateSourceError("SNAPSHOT_REQUEST_IDENTITY_MISMATCH")
        if request.source_endpoint_role != self.endpoint_role:
            raise RateSourceError("SNAPSHOT_ENDPOINT_ROLE_MISMATCH")
