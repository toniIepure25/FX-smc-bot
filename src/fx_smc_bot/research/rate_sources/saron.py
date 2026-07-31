"""SIX/SNB selected 18:00 SARON fixing adapter."""

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
