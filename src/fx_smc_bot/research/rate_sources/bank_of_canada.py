"""Bank of Canada V39079 policy-event adapter."""

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


class BankOfCanadaAdapter:
    adapter_id = "BOC_V39079_EVENTS_V1"
    currency = "CAD"
    series_id = "V39079"
    parser_version = "BOC_V39079_EVENT_JSON_V1"
    publisher = "Bank of Canada"
    endpoint_role = "official_policy_announcement_event_registry"
    schema_id = "boc-v39079-policy-events-official-v1"
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
            "announcementType",
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
                url="https://www.bankofcanada.ca/valet/observations/V39079/json",
                query_parameters={
                    "end_date": end.isoformat(),
                    "event_metadata": "policy-announcement",
                    "start_date": start.isoformat(),
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
                calendar_id="BANK_OF_CANADA_ANNOUNCEMENT_CALENDAR",
                metadata_fields=("announcementType",),
            )
            for row in rows
        )
        if any(
            dict(version.source_metadata)["announcementType"] != "POLICY_RATE_DECISION"
            for version in versions
        ):
            raise RateSourceError("BOC_NON_POLICY_EVENT_PROHIBITED")
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
            calendar_id="BANK_OF_CANADA_ANNOUNCEMENT_CALENDAR",
            publication_zone="America/Toronto",
            endpoint_roles=frozenset({self.endpoint_role}),
        )
        reasons = []
        if version.revision_status not in {"ORIGINAL", "CORRECTED"}:
            reasons.append("BOC_POLICY_EVENT_REVISION_STATUS_INVALID")
        if version.observation_date != version.publication_timestamp.date():
            reasons.append("BOC_EVENT_DATE_PUBLICATION_DATE_MISMATCH")
        return combine_certification(result, reasons)

    def _validate_snapshot(self, snapshot: SourceSnapshot) -> None:
        if (
            snapshot.request.adapter_id != self.adapter_id
            or snapshot.request.series_id != self.series_id
        ):
            raise RateSourceError("SNAPSHOT_REQUEST_IDENTITY_MISMATCH")
