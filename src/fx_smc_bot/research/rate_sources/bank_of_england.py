"""Bank of England IUDSOIA/SONIA adapter."""

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

SONIA_REFORM_START = date(2018, 4, 23)


class BankOfEnglandSoniaAdapter:
    adapter_id = "BOE_SONIA_V1"
    currency = "GBP"
    series_id = "IUDSOIA"
    parser_version = "BOE_IUDSOIA_JSON_V1"
    publisher = "Bank of England"
    endpoint_role = "official_iadb_export"
    schema_id = "boe-iudsoia-official-v1"
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
                url="https://www.bankofengland.co.uk/boeapps/database/_iadb-fromshowcolumns.asp",
                query_parameters={
                    "CSVF": "TN",
                    "Datefrom": start.strftime("%d/%b/%Y"),
                    "Dateto": end.strftime("%d/%b/%Y"),
                    "SeriesCodes": self.series_id,
                    "UsingCodes": "Y",
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
                calendar_id="LONDON_BUSINESS_DAY",
                metadata_fields=("methodologyRegime",),
            )
            for row in rows
        )
        for version in versions:
            regime = dict(version.source_metadata)["methodologyRegime"]
            expected = "REFORMED" if version.observation_date >= SONIA_REFORM_START else "LEGACY"
            if regime != expected:
                raise RateSourceError("SONIA_METHODOLOGY_REGIME_MISMATCH")
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
            calendar_id="LONDON_BUSINESS_DAY",
            publication_zone="Europe/London",
            endpoint_roles=frozenset({self.endpoint_role}),
        )
        local = version.strategy_availability_timestamp.astimezone(ZoneInfo("Europe/London"))
        reasons = []
        if version.observation_date >= SONIA_REFORM_START:
            if local.date() <= version.observation_date or (local.hour, local.minute) < (12, 0):
                reasons.append("REFORMED_SONIA_BEFORE_CONSERVATIVE_REVISION_ENVELOPE")
        elif local.date() != version.observation_date or (local.hour, local.minute) < (18, 0):
            reasons.append("LEGACY_SONIA_BEFORE_SAME_DAY_PUBLICATION")
        return combine_certification(result, reasons)

    def _validate_snapshot(self, snapshot: SourceSnapshot) -> None:
        if (
            snapshot.request.adapter_id != self.adapter_id
            or snapshot.request.series_id != self.series_id
        ):
            raise RateSourceError("SNAPSHOT_REQUEST_IDENTITY_MISMATCH")
