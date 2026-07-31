"""Bank of Japan final uncollateralized overnight call-rate adapter."""

from __future__ import annotations

from datetime import date

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


class BankOfJapanCallRateAdapter:
    adapter_id = "BOJ_FINAL_UO_CALL_V1"
    currency = "JPY"
    series_id = "FM01'STRDCLUCON"
    parser_version = "BOJ_FINAL_UO_CALL_JSON_V1"
    publisher = "Bank of Japan"
    endpoint_role = "official_time_series_export"
    schema_id = "boj-final-call-rate-official-v1"
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
            "resultType",
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
                url="https://www.stat-search.boj.or.jp/ssi/cgi-bin/famecgi2",
                query_parameters={
                    "code": self.series_id,
                    "endDate": end.isoformat(),
                    "format": "json",
                    "resultType": "final",
                    "startDate": start.isoformat(),
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
                day_count_convention="ACT_365_FIXED",
                calendar_id="TOKYO_BUSINESS_DAY",
                metadata_fields=("resultType",),
            )
            for row in rows
        )
        if any(dict(version.source_metadata)["resultType"] != "FINAL" for version in versions):
            raise RateSourceError("BOJ_PROVISIONAL_RATE_PROHIBITED")
        return reject_duplicate_versions(versions)

    def certify_version(self, version: RateVersion) -> RateCertification:
        result = certify_common(
            version,
            adapter_id=self.adapter_id,
            currency=self.currency,
            series_ids=frozenset({self.series_id}),
            publisher=self.publisher,
            parser_version=self.parser_version,
            day_count_convention="ACT_365_FIXED",
            calendar_id="TOKYO_BUSINESS_DAY",
            publication_zone="Asia/Tokyo",
            endpoint_roles=frozenset({self.endpoint_role}),
        )
        reasons = []
        if version.revision_status != "FINAL":
            reasons.append("BOJ_FINAL_RESULT_REQUIRED")
        if version.publication_timestamp.date() <= version.observation_date:
            reasons.append("BOJ_FINAL_PUBLICATION_MUST_FOLLOW_OBSERVATION_DATE")
        return combine_certification(result, reasons)

    def _validate_snapshot(self, snapshot: SourceSnapshot) -> None:
        if (
            snapshot.request.adapter_id != self.adapter_id
            or snapshot.request.series_id != self.series_id
        ):
            raise RateSourceError("SNAPSHOT_REQUEST_IDENTITY_MISMATCH")
