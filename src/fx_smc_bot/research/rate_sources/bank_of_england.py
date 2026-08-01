"""Bank of England IUDSOIA/SONIA adapter."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from fx_smc_bot.research.publication_censoring import (
    PublicationEvidenceKind,
    RevisionStatus,
    first_portfolio_execution_strictly_after,
)
from fx_smc_bot.research.rate_calendars import LONDON_BUSINESS_DAY, calendar_definition
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
    strict_csv_rows,
    strict_json_rows,
    validate_v2_snapshot,
    version_from_row,
)

LONDON_ZONE = ZoneInfo("Europe/London")
SONIA_REFORM_START = date(2018, 4, 23)
SONIA_FINAL_LEGACY_OBSERVATION = date(2018, 4, 20)
BOE_IADB_CSV_INSPECTOR_ID = "F0RPE2ERUSDSRLPAEURSRGBPSR_BOE_IADB_CSV_SHAPE_V1"
BOE_IUDSOIA_V3_SCHEMA_FINGERPRINT = (
    "0cabc3dd69e8438ec9acefd96e185571e19c829635034eb9df9e42e75238c8b8"
)
BOE_IADB_XML_V3_SCHEMA_FINGERPRINT = (
    "c6639197c0e3547b9cf605beb2f973d89052c9c30fa620d0df3abe200a67d438"
)
BOE_IADB_RESEARCH_USER_AGENT = (
    "FX-smc-bot-research/1.0 transparent-official-rate-certification"
)


@dataclass(frozen=True, slots=True)
class BoeIadbCsvShapeCertification:
    snapshot_sha256: str
    request_identity: str
    schema_fingerprint: str
    inspector_id: str
    row_container_path: str
    schema_role: str
    row_count: int


@dataclass(frozen=True, slots=True)
class BoePublicationEvidence:
    observation_date: date
    actual_publication_timestamp: datetime | None
    publication_lower_bound: datetime
    publication_upper_bound: datetime
    publication_upper_bound_exclusive: bool
    publication_evidence_kind: str
    publication_evidence_source: str
    effective_timestamp: datetime
    strategy_availability_timestamp: datetime


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


class BankOfEnglandSoniaAdapterV2(BankOfEnglandSoniaAdapter):
    """Future-baseline SONIA adapter pinned to a bounded IADB export."""

    adapter_id = "BOE_SONIA_V2"
    parser_version = "BOE_IUDSOIA_COLUMNAR_CSV_V2"
    schema_id = "BOE_IADB_COLUMNAR_CSV_V2"
    csv_fields = (
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
    )
    endpoint_declarations = (
        OfficialNumericalEndpoint(
            allowlist_identity="F0RPE2ER_OFFICIAL_SOURCE_ALLOWLIST_V1",
            adapter_id=adapter_id,
            currency=BankOfEnglandSoniaAdapter.currency,
            series_id=BankOfEnglandSoniaAdapter.series_id,
            publisher=BankOfEnglandSoniaAdapter.publisher,
            url="https://www.bankofengland.co.uk/boeapps/database/_iadb-fromshowcolumns.asp",
            start_parameter="Datefrom",
            end_parameter="Dateto",
            series_parameter="SeriesCodes",
            series_parameter_value="IUDSOIA",
            response_format="CSV_COLUMNAR",
            accept_media_type="text/csv",
            format_parameter="CSVF",
            format_parameter_value="TN",
            series_path_token=None,
            format_path_token=None,
            schema_id=schema_id,
            required_fields=tuple(sorted(BankOfEnglandSoniaAdapter.required_fields)),
            schema_fingerprint=schema_fingerprint(
                schema_id,
                BankOfEnglandSoniaAdapter.required_fields,
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
        validate_v2_snapshot(
            snapshot, adapter_id=self.adapter_id, declarations=self.endpoint_declarations
        )
        self._validate_snapshot(snapshot)
        rows = strict_csv_rows(snapshot, required_fields=self.csv_fields)
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


class BankOfEnglandSoniaAdapterV3(BankOfEnglandSoniaAdapter):
    """Official BOE IADB tabular CSV adapter with SONIA transition evidence."""

    adapter_id = "BOE_SONIA_V3"
    parser_version = "BOE_IUDSOIA_TABULAR_CSV_V3"
    schema_id = "BOE_IADB_TN_CSV_V3"
    csv_fields = ("DATE", "IUDSOIA")
    xml_fields = ("ObsDate", "ObsValue", "SeriesCode")
    endpoint_role = "official_iadb_machine_readable_export"
    endpoint_declarations = (
        OfficialNumericalEndpoint(
            allowlist_identity="F0RPE2ER_OFFICIAL_SOURCE_ALLOWLIST_V1",
            adapter_id=adapter_id,
            currency=BankOfEnglandSoniaAdapter.currency,
            series_id=BankOfEnglandSoniaAdapter.series_id,
            publisher=BankOfEnglandSoniaAdapter.publisher,
            url="https://www.bankofengland.co.uk/boeapps/database/_iadb-fromshowcolumns.asp",
            start_parameter="Datefrom",
            end_parameter="Dateto",
            series_parameter="SeriesCodes",
            series_parameter_value="IUDSOIA",
            response_format="CSV_TABULAR_NO_TITLES",
            accept_media_type="text/csv",
            format_parameter="CSVF",
            format_parameter_value="TN",
            series_path_token=None,
            format_path_token=None,
            schema_id=schema_id,
            required_fields=tuple(sorted(csv_fields)),
            schema_fingerprint=BOE_IUDSOIA_V3_SCHEMA_FINGERPRINT,
            publication_timestamp_field="BENCHMARK_PUBLICATION_RULE_DERIVED",
            effective_timestamp_field="DATE_DERIVED",
        ),
        OfficialNumericalEndpoint(
            allowlist_identity="F0RPE2ER_OFFICIAL_SOURCE_ALLOWLIST_V1",
            adapter_id=adapter_id,
            currency=BankOfEnglandSoniaAdapter.currency,
            series_id=BankOfEnglandSoniaAdapter.series_id,
            publisher=BankOfEnglandSoniaAdapter.publisher,
            url="https://www.bankofengland.co.uk/boeapps/database/_iadb-fromshowcolumns.asp",
            start_parameter="Datefrom",
            end_parameter="Dateto",
            series_parameter="SeriesCodes",
            series_parameter_value="IUDSOIA",
            response_format="XML_IADB",
            accept_media_type="application/xml",
            format_parameter="xml.x",
            format_parameter_value="yes",
            series_path_token=None,
            format_path_token=None,
            schema_id="BOE_IADB_XML_V3",
            required_fields=tuple(sorted(xml_fields)),
            schema_fingerprint=BOE_IADB_XML_V3_SCHEMA_FINGERPRINT,
            publication_timestamp_field="BENCHMARK_PUBLICATION_RULE_DERIVED",
            effective_timestamp_field="ObsDate_DERIVED",
        ),
    )

    def build_requests(
        self, start: date, end: date, authorization: RateAccessAuthorization
    ) -> tuple[OfficialRateRequest, ...]:
        return (self.build_csv_request(start, end, authorization),)

    def build_csv_request(
        self, start: date, end: date, authorization: RateAccessAuthorization
    ) -> OfficialRateRequest:
        return self._boe_v3_request(
            self.endpoint_declarations[0],
            start,
            end,
            {
                "CSVF": "TN",
                "Datefrom": start.strftime("%d/%b/%Y"),
                "Dateto": end.strftime("%d/%b/%Y"),
                "SeriesCodes": self.series_id,
                "UsingCodes": "Y",
                "VFD": "Y",
                "VPD": "N",
                "csv.x": "yes",
            },
            authorization,
        )

    def build_xml_fallback_request(
        self, start: date, end: date, authorization: RateAccessAuthorization
    ) -> OfficialRateRequest:
        return self._boe_v3_request(
            self.endpoint_declarations[1],
            start,
            end,
            {
                "CodeVer": "new",
                "Datefrom": start.strftime("%d/%b/%Y"),
                "Dateto": end.strftime("%d/%b/%Y"),
                "SeriesCodes": self.series_id,
                "VFD": "Y",
                "VPD": "N",
                "xml.x": "yes",
            },
            authorization,
        )

    def build_fallback_requests_after_csv_failure(
        self, start: date, end: date, authorization: RateAccessAuthorization, failure: str
    ) -> tuple[OfficialRateRequest, ...]:
        if failure not in {
            "OFFICIAL_ENDPOINT_HTTP_STATUS_403",
            "BOE_IADB_CSV_SCHEMA_CHANGED",
            "INVALID_BOE_IADB_CSV",
        }:
            return ()
        return (self.build_xml_fallback_request(start, end, authorization),)

    def certify_snapshot_shape(self, snapshot: SourceSnapshot) -> BoeIadbCsvShapeCertification:
        declaration = validate_v2_snapshot(
            snapshot, adapter_id=self.adapter_id, declarations=self.endpoint_declarations
        )
        if declaration.response_format != "CSV_TABULAR_NO_TITLES":
            raise RateSourceError("BOE_XML_SHAPE_CERTIFICATION_NOT_ACTIVE")
        self._validate_csv_request(snapshot.request)
        rows = _strict_boe_iadb_csv_rows(snapshot, required_fields=self.csv_fields)
        for row in rows:
            self._validate_csv_scope(row, request=snapshot.request)
        if not rows:
            raise RateSourceError("BOE_IADB_ROWS_REQUIRED")
        return BoeIadbCsvShapeCertification(
            snapshot_sha256=snapshot.source_snapshot_sha256,
            request_identity=snapshot.request.request_identity,
            schema_fingerprint=BOE_IUDSOIA_V3_SCHEMA_FINGERPRINT,
            inspector_id=BOE_IADB_CSV_INSPECTOR_ID,
            row_container_path="$.iadb_tabular_csv_rows",
            schema_role="IUDSOIA_TABULAR_NO_TITLES_CSV",
            row_count=len(rows),
        )

    def parse_snapshot(self, snapshot: SourceSnapshot) -> tuple[RateVersion, ...]:
        certification = self.certify_snapshot_shape(snapshot)
        rows = _strict_boe_iadb_csv_rows(snapshot, required_fields=self.csv_fields)
        versions: dict[date, RateVersion] = {}
        for ordinal, row in enumerate(rows):
            version = self._version_from_csv_row(
                snapshot,
                row,
                source_row_ordinal=ordinal,
                schema_fingerprint=certification.schema_fingerprint,
            )
            previous = versions.get(version.observation_date)
            if previous is not None:
                if self._semantic_version_record(previous) != self._semantic_version_record(
                    version
                ):
                    raise RateSourceError("CONFLICTING_FINAL_HISTORY_SONIA_ROWS")
                continue
            versions[version.observation_date] = version
        if not versions:
            raise RateSourceError("BOE_IADB_ROWS_REQUIRED")
        return tuple(versions[day] for day in sorted(versions))

    def certify_version(self, version: RateVersion) -> RateCertification:
        reasons: list[str] = []
        if version.currency != self.currency or version.series_id != self.series_id:
            reasons.append("IDENTITY_MISMATCH")
        if version.source_publisher != self.publisher:
            reasons.append("PUBLISHER_MISMATCH")
        if version.parser_version != self.parser_version:
            reasons.append("PARSER_VERSION_MISMATCH")
        if version.schema_fingerprint != BOE_IUDSOIA_V3_SCHEMA_FINGERPRINT:
            reasons.append("SCHEMA_FINGERPRINT_MISMATCH")
        try:
            expected = sonia_publication_evidence(version.observation_date)
        except RateSourceError as exc:
            reasons.append(str(exc))
            expected = None
        if expected is not None:
            if version.publication_timestamp != expected.actual_publication_timestamp:
                reasons.append("ACTUAL_PUBLICATION_TIMESTAMP_MISMATCH")
            if (
                version.resolved_publication_lower_bound
                != expected.publication_lower_bound
                or version.resolved_publication_upper_bound
                != expected.publication_upper_bound
                or version.publication_upper_bound_exclusive
                != expected.publication_upper_bound_exclusive
                or version.publication_evidence_kind
                != expected.publication_evidence_kind
                or version.publication_evidence_source
                != expected.publication_evidence_source
            ):
                reasons.append("PUBLICATION_BOUNDS_MISMATCH")
            if version.effective_timestamp != expected.effective_timestamp:
                reasons.append("EFFECTIVE_TIMESTAMP_MISMATCH")
            if version.strategy_availability_timestamp != (
                expected.strategy_availability_timestamp
            ):
                reasons.append("STRATEGY_AVAILABILITY_MISMATCH")
        if version.revision_identifier is not None or version.revision_status != (
            RevisionStatus.FINAL_HISTORY_ONLY_NO_EXPLICIT_REVISION_ID.value
        ):
            reasons.append("FINAL_HISTORY_REVISION_SEMANTICS_MISMATCH")
        if version.day_count_convention != "ACT_365_FIXED":
            reasons.append("DAY_COUNT_MISMATCH")
        if version.calendar_id != LONDON_BUSINESS_DAY:
            reasons.append("CALENDAR_MISMATCH")
        return RateCertification(
            adapter_id=self.adapter_id,
            identity=version.identity,
            revision_identifier=version.revision_identifier,
            passed=not reasons,
            status="PASS" if not reasons else "BLOCKED_BY_OFFICIAL_RATE_ADAPTER",
            checks=(
                "BOE_SOURCE_IDENTITY",
                "IADB_TABULAR_CSV_SCHEMA",
                "UNIT_CONVERSION",
                "LEGACY_PUBLICATION_AVAILABILITY",
                "REFORMED_PUBLICATION_AVAILABILITY",
                "REVISION_NULLABILITY",
                "SONIA_METHOD_TRANSITION",
                "LONDON_CALENDAR",
            ),
            reasons=tuple(reasons),
        )

    @staticmethod
    def _boe_v3_request(
        declaration: OfficialNumericalEndpoint,
        start: date,
        end: date,
        query_parameters: Mapping[str, str],
        authorization: RateAccessAuthorization,
    ) -> OfficialRateRequest:
        request = OfficialRateRequest(
            adapter_id=declaration.adapter_id,
            currency=declaration.currency,
            series_id=declaration.series_id,
            source_publisher=declaration.publisher,
            source_endpoint_role="official_iadb_machine_readable_export",
            start=start,
            end=end,
            url=declaration.url,
            query_parameters=tuple(sorted(query_parameters.items())),
            request_headers=(
                ("Accept", declaration.accept_media_type),
                ("User-Agent", BOE_IADB_RESEARCH_USER_AGENT),
            ),
            endpoint_declaration=declaration,
        )
        authorization.authorize(request)
        return request

    @staticmethod
    def _validate_csv_request(request: OfficialRateRequest) -> None:
        parameters = dict(request.query_parameters)
        required = {
            "CSVF": "TN",
            "SeriesCodes": "IUDSOIA",
            "UsingCodes": "Y",
            "VFD": "Y",
            "VPD": "N",
            "csv.x": "yes",
        }
        if any(parameters.get(key) != value for key, value in required.items()):
            raise RateSourceError("BOE_IADB_CSV_REQUEST_IDENTITY_MISMATCH")
        headers = dict(request.request_headers)
        if headers.get("Accept") != "text/csv":
            raise RateSourceError("BOE_IADB_CSV_ACCEPT_HEADER_MISMATCH")
        prohibited = {"Cookie", "Referer", "Sec-Fetch-Site", "Sec-Fetch-Mode"}
        if any(name in headers for name in prohibited):
            raise RateSourceError("BOE_IADB_BROWSER_IMPERSONATION_HEADER_PROHIBITED")
        user_agent = headers.get("User-Agent", "")
        if "Mozilla/" in user_agent or "Chrome/" in user_agent or "Safari/" in user_agent:
            raise RateSourceError("BOE_IADB_BROWSER_IMPERSONATION_HEADER_PROHIBITED")

    @staticmethod
    def _validate_csv_scope(row: Mapping[str, object], *, request: OfficialRateRequest) -> date:
        if request.series_id != "IUDSOIA":
            raise RateSourceError("BOE_IUDSOIA_REQUEST_REQUIRED")
        observed = _parse_boe_date(required_boe_text(row, "DATE"))
        if observed < request.start or observed > request.end:
            raise RateSourceError("BOE_IADB_OBSERVATION_OUTSIDE_REQUEST_BOUNDS")
        if observed > date(2022, 12, 31):
            raise RateSourceError("BOE_IADB_OBSERVATION_OUTSIDE_AUTHORIZED_SCOPE")
        if not calendar_definition(LONDON_BUSINESS_DAY).is_open(observed):
            raise RateSourceError("BOE_IADB_NON_BUSINESS_DAY_OBSERVATION")
        return observed

    def _version_from_csv_row(
        self,
        snapshot: SourceSnapshot,
        row: Mapping[str, object],
        *,
        source_row_ordinal: int,
        schema_fingerprint: str,
    ) -> RateVersion:
        if schema_fingerprint != BOE_IUDSOIA_V3_SCHEMA_FINGERPRINT:
            raise RateSourceError("UNKNOWN_BOE_IADB_SCHEMA_FINGERPRINT")
        observation = self._validate_csv_scope(row, request=snapshot.request)
        evidence = sonia_publication_evidence(observation)
        value = _decimal_percent_to_float(row.get("IUDSOIA"))
        source_document_id = _source_document_id(snapshot)
        metadata = (
            ("csv_format", "TABULAR_NO_TITLES"),
            (
                "methodologyRegime",
                "LEGACY_SONIA"
                if observation <= SONIA_FINAL_LEGACY_OBSERVATION
                else "REFORMED_SONIA",
            ),
            ("series_column", "IUDSOIA"),
        )
        return RateVersion(
            currency=self.currency,
            series_id=self.series_id,
            observation_date=observation,
            value=value,
            publication_timestamp=evidence.actual_publication_timestamp,
            effective_timestamp=evidence.effective_timestamp,
            strategy_availability_timestamp=evidence.strategy_availability_timestamp,
            source_publisher=self.publisher,
            source_document_id=source_document_id,
            source_endpoint_role=snapshot.request.source_endpoint_role,
            source_snapshot_sha256=snapshot.source_snapshot_sha256,
            parser_version=self.parser_version,
            revision_identifier=None,
            revision_status=(
                RevisionStatus.FINAL_HISTORY_ONLY_NO_EXPLICIT_REVISION_ID.value
            ),
            day_count_convention="ACT_365_FIXED",
            calendar_id=LONDON_BUSINESS_DAY,
            retrieved_at=snapshot.retrieved_at,
            source_metadata=metadata,
            publication_lower_bound=evidence.publication_lower_bound,
            publication_upper_bound=evidence.publication_upper_bound,
            publication_upper_bound_exclusive=evidence.publication_upper_bound_exclusive,
            publication_evidence_kind=evidence.publication_evidence_kind,
            publication_evidence_source=evidence.publication_evidence_source,
            schema_fingerprint=schema_fingerprint,
            source_row_ordinal=source_row_ordinal,
            source_adapter_id=snapshot.request.adapter_id,
            source_request_identity=snapshot.request.request_identity,
        )

    @staticmethod
    def _semantic_version_record(version: RateVersion) -> tuple[object, ...]:
        return (
            version.identity,
            version.value,
            version.publication_timestamp,
            version.resolved_publication_lower_bound,
            version.resolved_publication_upper_bound,
            version.strategy_availability_timestamp,
            version.revision_identifier,
            version.revision_status,
            version.schema_fingerprint,
            version.source_metadata,
        )


def sonia_publication_evidence(observation: date) -> BoePublicationEvidence:
    if observation <= SONIA_FINAL_LEGACY_OBSERVATION:
        return legacy_sonia_publication_evidence(observation)
    if observation >= SONIA_REFORM_START:
        return reformed_sonia_publication_evidence(observation)
    raise RateSourceError("SONIA_WEEKEND_TRANSITION_HAS_NO_SYNTHETIC_OBSERVATION")


def legacy_sonia_publication_evidence(observation: date) -> BoePublicationEvidence:
    if observation > SONIA_FINAL_LEGACY_OBSERVATION:
        raise RateSourceError("LEGACY_SONIA_AFTER_FROZEN_TRANSITION")
    lower = datetime.combine(observation, time(18, 0), tzinfo=LONDON_ZONE)
    upper = datetime.combine(observation + timedelta(days=1), time.min, tzinfo=LONDON_ZONE)
    effective = datetime.combine(observation, time.min, tzinfo=LONDON_ZONE)
    return BoePublicationEvidence(
        observation_date=observation,
        actual_publication_timestamp=None,
        publication_lower_bound=lower,
        publication_upper_bound=upper,
        publication_upper_bound_exclusive=True,
        publication_evidence_kind=PublicationEvidenceKind.PUBLICATION_DAY_ENVELOPE.value,
        publication_evidence_source="BOE_LEGACY_SONIA_SAME_DAY_18_00_PUBLICATION_ENVELOPE_V1",
        effective_timestamp=effective,
        strategy_availability_timestamp=first_portfolio_execution_strictly_after(upper),
    )


def reformed_sonia_publication_evidence(observation: date) -> BoePublicationEvidence:
    if observation < SONIA_REFORM_START:
        raise RateSourceError("REFORMED_SONIA_BEFORE_FROZEN_TRANSITION")
    publication_day = _next_london_business_day(observation + timedelta(days=1))
    lower = datetime.combine(publication_day, time(9, 0), tzinfo=LONDON_ZONE)
    upper = datetime.combine(publication_day, time(12, 0), tzinfo=LONDON_ZONE)
    effective = datetime.combine(observation, time.min, tzinfo=LONDON_ZONE)
    return BoePublicationEvidence(
        observation_date=observation,
        actual_publication_timestamp=None,
        publication_lower_bound=lower,
        publication_upper_bound=upper,
        publication_upper_bound_exclusive=False,
        publication_evidence_kind=PublicationEvidenceKind.BOUNDED_TIME_ENVELOPE.value,
        publication_evidence_source="BOE_REFORMED_SONIA_T_PLUS_1_09_00_TO_12_00_ENVELOPE_V1",
        effective_timestamp=effective,
        strategy_availability_timestamp=upper,
    )


def _next_london_business_day(day: date) -> date:
    calendar = calendar_definition(LONDON_BUSINESS_DAY)
    candidate = day
    while not calendar.is_open(candidate):
        candidate += timedelta(days=1)
    return candidate


def _strict_boe_iadb_csv_rows(
    snapshot: SourceSnapshot,
    *,
    required_fields: tuple[str, ...],
) -> tuple[Mapping[str, object], ...]:
    content_type = snapshot.content_type.partition(";")[0].strip().lower()
    if content_type not in {"text/csv", "application/csv"}:
        raise RateSourceError("BOE_IADB_UNEXPECTED_CONTENT_TYPE")
    try:
        text = snapshot.payload.decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(text), strict=True)
        if tuple(reader.fieldnames or ()) != required_fields:
            raise RateSourceError("BOE_IADB_CSV_SCHEMA_CHANGED")
        rows = tuple(dict(row) for row in reader)
    except (UnicodeDecodeError, csv.Error) as exc:
        raise RateSourceError("INVALID_BOE_IADB_CSV") from exc
    return rows


def required_boe_text(row: Mapping[str, object], field_name: str) -> str:
    value = row.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise RateSourceError(f"BOE_{field_name}_REQUIRED")
    return value.strip()


def _parse_boe_date(value: str) -> date:
    for pattern in ("%d %b %Y", "%d/%b/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, pattern).date()
        except ValueError:
            continue
    raise RateSourceError("INVALID_BOE_IADB_DATE")


def _decimal_percent_to_float(value: object) -> float:
    if not isinstance(value, str) or not value.strip():
        raise RateSourceError("BOE_IUDSOIA_VALUE_REQUIRED")
    try:
        result = Decimal(value) / Decimal("100")
    except InvalidOperation as exc:
        raise RateSourceError("INVALID_BOE_IUDSOIA_VALUE") from exc
    parsed = float(result)
    if not math.isfinite(parsed):
        raise RateSourceError("NON_FINITE_BOE_RATE")
    return parsed


def _source_document_id(snapshot: SourceSnapshot) -> str:
    record = {
        "endpoint": snapshot.request.url,
        "request_identity": snapshot.request.request_identity,
        "snapshot_sha256": snapshot.source_snapshot_sha256,
    }
    encoded = json.dumps(record, sort_keys=True, separators=(",", ":")).encode()
    return f"BOE_IUDSOIA:{hashlib.sha256(encoded).hexdigest()}"
