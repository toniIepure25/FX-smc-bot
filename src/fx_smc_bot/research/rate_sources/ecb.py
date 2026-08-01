"""ECB EONIA-to-euro-short-term-rate transition adapter."""

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
)
from fx_smc_bot.research.rate_calendars import TARGET2, calendar_definition
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
    parse_date,
    reject_duplicate_versions,
    schema_fingerprint,
    strict_json_rows,
    validate_v2_snapshot,
    version_from_row,
)

EONIA_END = date(2019, 9, 30)
ESTR_START = date(2019, 10, 1)
ECB_SDMX_CSV_INSPECTOR_ID = "F0RPE2ERUSDSRLPAEURSR_ECB_SDMX_CSV_SHAPE_V1"
EONIA_V3_SCHEMA_FINGERPRINT = (
    "10cdca98c037c6a6b4e61ccb9dbaa868a2bca5d6d9c3783ca60f7ab4f76a66ac"
)
ESTR_V3_SCHEMA_FINGERPRINT = (
    "9bf2e1d2c40d883fe0da3543e6d4d8eb461b3e973488d419d6e397ab0c8e6dca"
)
EONIA_V3_KEY = "EON.D.EONIA_TO.RATE"
ESTR_V3_KEY = "EST.B.EU000A2X2A25.WT"
BRUSSELS_ZONE = ZoneInfo("Europe/Brussels")


@dataclass(frozen=True, slots=True)
class EcbSdmxCsvShapeCertification:
    snapshot_sha256: str
    request_identity: str
    schema_fingerprint: str
    inspector_id: str
    row_container_path: str
    schema_role: str
    row_count: int


@dataclass(frozen=True, slots=True)
class EcbPublicationEvidence:
    observation_date: date
    actual_publication_timestamp: datetime | None
    publication_lower_bound: datetime
    publication_upper_bound: datetime
    publication_upper_bound_exclusive: bool
    publication_evidence_kind: str
    publication_evidence_source: str
    effective_timestamp: datetime
    strategy_availability_timestamp: datetime


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
            and version.publication_timestamp is not None
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


class EcbEoniaEstrAdapterV3(EcbEoniaEstrAdapterV2):
    """Publication-safe ECB SDMX CSV adapter with corrected EONIA identity."""

    adapter_id = "ECB_EONIA_ESTR_V3"
    parser_version = "ECB_EONIA_ESTR_SDMX_CSV_V3"
    schema_id = "ECB_EONIA_ESTR_SDMX_CSV_V3"
    publisher = EcbEoniaEstrAdapter.publisher
    eonia_fields = (
        "KEY",
        "FREQ",
        "EONIA_BANK",
        "EONIA_ITEM",
        "TIME_PERIOD",
        "OBS_VALUE",
        "OBS_STATUS",
        "OBS_CONF",
        "OBS_PRE_BREAK",
        "OBS_COM",
        "TIME_FORMAT",
        "BREAKS",
        "COLLECTION",
        "COMPILING_ORG",
        "DISS_ORG",
        "PUBL_ECB",
        "PUBL_MU",
        "PUBL_PUBLIC",
        "COMPILATION",
        "DECIMALS",
        "SOURCE_AGENCY",
        "TITLE",
        "TITLE_COMPL",
        "UNIT",
        "UNIT_MULT",
    )
    estr_fields = (
        "KEY",
        "FREQ",
        "BENCHMARK_ITEM",
        "DATA_TYPE_EST",
        "TIME_PERIOD",
        "OBS_VALUE",
        "OBS_STATUS",
        "CONF_STATUS",
        "PRE_BREAK_VALUE",
        "COMMENT_OBS",
        "CALCUL_START_DATE",
        "CALCUL_END_DATE",
        "TIME_FORMAT",
        "BREAKS",
        "COMMENT_TS",
        "COMPILING_ORG",
        "COVERAGE",
        "DATA_COMP",
        "DECIMALS",
        "DISS_ORG",
        "PUBL_ECB",
        "PUBL_MU",
        "PUBL_PUBLIC",
        "TIME_PER_COLLECT",
        "TITLE",
        "TITLE_COMPL",
        "UNIT_INDEX_BASE",
        "UNIT_MEASURE",
        "UNIT_MULT",
    )
    endpoint_declarations = (
        OfficialNumericalEndpoint(
            allowlist_identity="F0RPE2ER_OFFICIAL_SOURCE_ALLOWLIST_V1",
            adapter_id=adapter_id,
            currency=EcbEoniaEstrAdapter.currency,
            series_id="EONIA",
            publisher=publisher,
            url="https://data-api.ecb.europa.eu/service/data/EON/D.EONIA_TO.RATE",
            start_parameter="startPeriod",
            end_parameter="endPeriod",
            series_parameter="PATH_SERIES_KEY",
            series_parameter_value="EONIA",
            response_format="CSV_SDMX",
            accept_media_type="text/csv",
            format_parameter="format",
            format_parameter_value="csvdata",
            series_path_token="/data/EON/D.EONIA_TO.RATE",
            format_path_token=None,
            schema_id="ECB_EONIA_SDMX_CSV_V3",
            required_fields=tuple(sorted(eonia_fields)),
            schema_fingerprint=schema_fingerprint(
                "ECB_EONIA_SDMX_CSV_V3", frozenset(eonia_fields)
            ),
            publication_timestamp_field="BENCHMARK_PUBLICATION_RULE_19_00_EUROPE",
            effective_timestamp_field="TIME_PERIOD_DERIVED",
        ),
        OfficialNumericalEndpoint(
            allowlist_identity="F0RPE2ER_OFFICIAL_SOURCE_ALLOWLIST_V1",
            adapter_id=adapter_id,
            currency=EcbEoniaEstrAdapter.currency,
            series_id="ESTR",
            publisher=publisher,
            url="https://data-api.ecb.europa.eu/service/data/EST/B.EU000A2X2A25.WT",
            start_parameter="startPeriod",
            end_parameter="endPeriod",
            series_parameter="PATH_SERIES_KEY",
            series_parameter_value="ESTR",
            response_format="CSV_SDMX",
            accept_media_type="text/csv",
            format_parameter="format",
            format_parameter_value="csvdata",
            series_path_token="/data/EST/B.EU000A2X2A25.WT",
            format_path_token=None,
            schema_id="ECB_ESTR_SDMX_CSV_V3",
            required_fields=tuple(sorted(estr_fields)),
            schema_fingerprint=schema_fingerprint(
                "ECB_ESTR_SDMX_CSV_V3", frozenset(estr_fields)
            ),
            publication_timestamp_field="BENCHMARK_PUBLICATION_BOUNDARY_09_00_EUROPE",
            effective_timestamp_field="TIME_PERIOD_DERIVED",
        ),
    )

    def build_requests(
        self, start: date, end: date, authorization: RateAccessAuthorization
    ) -> tuple[OfficialRateRequest, ...]:
        if start > end:
            raise RateSourceError("REQUEST_INTERVAL_INVALID")
        requests: list[OfficialRateRequest] = []
        if start <= EONIA_END:
            requests.append(
                self._v3_request("EONIA", start, min(end, EONIA_END), authorization)
            )
        if end >= ESTR_START:
            requests.append(
                self._v3_request("ESTR", max(start, ESTR_START), end, authorization)
            )
        return tuple(requests)

    def certify_snapshot_shape(self, snapshot: SourceSnapshot) -> EcbSdmxCsvShapeCertification:
        declaration = validate_v2_snapshot(
            snapshot, adapter_id=self.adapter_id, declarations=self.endpoint_declarations
        )
        required_fields = (
            self.eonia_fields if declaration.series_id == "EONIA" else self.estr_fields
        )
        rows = _strict_sdmx_csv_rows(snapshot, required_fields=required_fields)
        expected_key = EONIA_V3_KEY if declaration.series_id == "EONIA" else ESTR_V3_KEY
        expected_freq = "D" if declaration.series_id == "EONIA" else "B"
        expected_fingerprint = (
            EONIA_V3_SCHEMA_FINGERPRINT
            if declaration.series_id == "EONIA"
            else ESTR_V3_SCHEMA_FINGERPRINT
        )
        for row in rows:
            self._validate_sdmx_scope(
                row,
                expected_key=expected_key,
                expected_freq=expected_freq,
                request=snapshot.request,
            )
        return EcbSdmxCsvShapeCertification(
            snapshot_sha256=snapshot.source_snapshot_sha256,
            request_identity=snapshot.request.request_identity,
            schema_fingerprint=expected_fingerprint,
            inspector_id=ECB_SDMX_CSV_INSPECTOR_ID,
            row_container_path="$.sdmx_csv_rows",
            schema_role=f"{declaration.series_id}_SDMX_CSV",
            row_count=len(rows),
        )

    def parse_snapshot(self, snapshot: SourceSnapshot) -> tuple[RateVersion, ...]:
        certification = self.certify_snapshot_shape(snapshot)
        declaration = snapshot.request.endpoint_declaration
        if declaration is None:
            raise RateSourceError("ECB_V3_ENDPOINT_DECLARATION_REQUIRED")
        rows = _strict_sdmx_csv_rows(
            snapshot,
            required_fields=(
                self.eonia_fields if declaration.series_id == "EONIA" else self.estr_fields
            ),
        )
        versions: dict[date, RateVersion] = {}
        for ordinal, row in enumerate(rows):
            version = self._version_from_sdmx_row(
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
                    raise RateSourceError("CONFLICTING_FINAL_HISTORY_ECB_ROWS")
                continue
            versions[version.observation_date] = version
        if not versions:
            raise RateSourceError("ECB_V3_ROWS_REQUIRED")
        return tuple(versions[day] for day in sorted(versions))

    def certify_version(self, version: RateVersion) -> RateCertification:
        reasons: list[str] = []
        if version.currency != self.currency or version.series_id not in {"EONIA", "ESTR"}:
            reasons.append("IDENTITY_MISMATCH")
        if version.source_publisher != self.publisher:
            reasons.append("PUBLISHER_MISMATCH")
        if version.parser_version != self.parser_version:
            reasons.append("PARSER_VERSION_MISMATCH")
        if version.series_id == "EONIA":
            if version.observation_date > EONIA_END:
                reasons.append("EONIA_AFTER_FROZEN_TRANSITION")
            expected_fingerprint = EONIA_V3_SCHEMA_FINGERPRINT
            expected_evidence = eonia_publication_evidence(version.observation_date)
            expected_kind = PublicationEvidenceKind.EXACT_TIMESTAMP.value
        elif version.series_id == "ESTR":
            if version.observation_date < ESTR_START:
                reasons.append("ESTR_BEFORE_FROZEN_TRANSITION")
            expected_fingerprint = ESTR_V3_SCHEMA_FINGERPRINT
            expected_evidence = estr_publication_evidence(version.observation_date)
            expected_kind = PublicationEvidenceKind.BOUNDED_TIME_ENVELOPE.value
        else:
            expected_fingerprint = ""
            expected_evidence = eonia_publication_evidence(version.observation_date)
            expected_kind = ""
        if version.schema_fingerprint != expected_fingerprint:
            reasons.append("SCHEMA_FINGERPRINT_MISMATCH")
        if version.publication_evidence_kind != expected_kind:
            reasons.append("PUBLICATION_EVIDENCE_KIND_MISMATCH")
        if (
            version.resolved_publication_lower_bound
            != expected_evidence.publication_lower_bound
            or version.resolved_publication_upper_bound
            != expected_evidence.publication_upper_bound
            or version.publication_upper_bound_exclusive
            != expected_evidence.publication_upper_bound_exclusive
            or version.publication_evidence_source
            != expected_evidence.publication_evidence_source
        ):
            reasons.append("PUBLICATION_BOUNDS_MISMATCH")
        if version.effective_timestamp != expected_evidence.effective_timestamp:
            reasons.append("EFFECTIVE_TIMESTAMP_MISMATCH")
        if (
            version.strategy_availability_timestamp
            != expected_evidence.strategy_availability_timestamp
        ):
            reasons.append("STRATEGY_AVAILABILITY_MISMATCH")
        if version.series_id == "EONIA" and version.publication_timestamp != (
            expected_evidence.actual_publication_timestamp
        ):
            reasons.append("EONIA_ACTUAL_PUBLICATION_TIMESTAMP_MISMATCH")
        if version.series_id == "ESTR" and version.publication_timestamp is not None:
            reasons.append("ESTR_BOUNDED_PUBLICATION_MUST_NOT_CLAIM_ACTUAL_TIMESTAMP")
        if version.revision_identifier is not None or version.revision_status != (
            RevisionStatus.FINAL_HISTORY_ONLY_NO_EXPLICIT_REVISION_ID.value
        ):
            reasons.append("FINAL_HISTORY_REVISION_SEMANTICS_MISMATCH")
        if version.day_count_convention != "ACT_360" or version.calendar_id != TARGET2:
            reasons.append("CALENDAR_OR_DAY_COUNT_MISMATCH")
        return RateCertification(
            adapter_id=self.adapter_id,
            identity=version.identity,
            revision_identifier=version.revision_identifier,
            passed=not reasons,
            status="PASS" if not reasons else "BLOCKED_BY_OFFICIAL_RATE_ADAPTER",
            checks=(
                "ECB_SOURCE_IDENTITY",
                "SDMX_SCHEMA",
                "UNIT_CONVERSION",
                "PUBLICATION_AVAILABILITY",
                "REVISION_NULLABILITY",
                "EONIA_ESTR_TRANSITION",
                "TARGET2_CALENDAR",
            ),
            reasons=tuple(reasons),
        )

    def _v3_request(
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
                "format": "csvdata",
                "startPeriod": start.isoformat(),
            },
            authorization=authorization,
        )

    @staticmethod
    def _validate_sdmx_scope(
        row: Mapping[str, object],
        *,
        expected_key: str,
        expected_freq: str,
        request: OfficialRateRequest,
    ) -> date:
        key = required_sdmx_text(row, "KEY")
        freq = required_sdmx_text(row, "FREQ")
        if key != expected_key:
            raise RateSourceError("ECB_SDMX_KEY_MISMATCH")
        if freq != expected_freq:
            raise RateSourceError("ECB_SDMX_FREQ_MISMATCH")
        if "NZD" in key.upper():
            raise RateSourceError("NZD_RESPONSE_PROHIBITED")
        observed = parse_date(row.get("TIME_PERIOD"))
        if observed < request.start or observed > request.end:
            raise RateSourceError("ECB_TIME_PERIOD_OUTSIDE_REQUEST_BOUNDS")
        if observed > date(2022, 12, 31):
            raise RateSourceError("ECB_TIME_PERIOD_OUTSIDE_AUTHORIZED_SCOPE")
        return observed

    def _version_from_sdmx_row(
        self,
        snapshot: SourceSnapshot,
        row: Mapping[str, object],
        *,
        source_row_ordinal: int,
        schema_fingerprint: str,
    ) -> RateVersion:
        key = required_sdmx_text(row, "KEY")
        if key == EONIA_V3_KEY:
            series_id = "EONIA"
            expected_freq = "D"
            expected_fingerprint = EONIA_V3_SCHEMA_FINGERPRINT
            evidence = eonia_publication_evidence(
                self._validate_sdmx_scope(
                    row,
                    expected_key=EONIA_V3_KEY,
                    expected_freq=expected_freq,
                    request=snapshot.request,
                )
            )
            if evidence.observation_date > EONIA_END:
                raise RateSourceError("PRIMARY_EONIA_AFTER_TRANSITION_REJECTED")
        elif key == ESTR_V3_KEY:
            series_id = "ESTR"
            expected_freq = "B"
            if required_sdmx_text(row, "BENCHMARK_ITEM") != "EU000A2X2A25":
                raise RateSourceError("ECB_ESTR_BENCHMARK_ITEM_MISMATCH")
            if required_sdmx_text(row, "DATA_TYPE_EST") != "WT":
                raise RateSourceError("ECB_ESTR_DATA_TYPE_MISMATCH")
            expected_fingerprint = ESTR_V3_SCHEMA_FINGERPRINT
            evidence = estr_publication_evidence(
                self._validate_sdmx_scope(
                    row,
                    expected_key=ESTR_V3_KEY,
                    expected_freq=expected_freq,
                    request=snapshot.request,
                )
            )
            if evidence.observation_date < ESTR_START:
                raise RateSourceError("PRIMARY_ESTR_BEFORE_TRANSITION_REJECTED")
        else:
            raise RateSourceError("ECB_SDMX_KEY_MISMATCH")
        if schema_fingerprint != expected_fingerprint:
            raise RateSourceError("ECB_SDMX_SCHEMA_FINGERPRINT_MISMATCH")
        value = _decimal_percent_to_float(row.get("OBS_VALUE"))
        metadata = tuple(
            sorted(
                (str(field), str(raw))
                for field, raw in row.items()
                if field not in {"OBS_VALUE", "TIME_PERIOD"}
                and raw not in (None, "")
            )
        )
        source_document_id = _source_document_id(snapshot)
        return RateVersion(
            currency=self.currency,
            series_id=series_id,
            observation_date=evidence.observation_date,
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
            day_count_convention="ACT_360",
            calendar_id=TARGET2,
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


def eonia_publication_evidence(observation: date) -> EcbPublicationEvidence:
    publication = datetime.combine(observation, time(19, 0), tzinfo=BRUSSELS_ZONE)
    effective = datetime.combine(observation, time(0, 0), tzinfo=BRUSSELS_ZONE)
    return EcbPublicationEvidence(
        observation_date=observation,
        actual_publication_timestamp=publication,
        publication_lower_bound=publication,
        publication_upper_bound=publication,
        publication_upper_bound_exclusive=False,
        publication_evidence_kind=PublicationEvidenceKind.EXACT_TIMESTAMP.value,
        publication_evidence_source="ECB_EONIA_HISTORICAL_SAME_DAY_19_00_RULE",
        effective_timestamp=effective,
        strategy_availability_timestamp=max(publication, effective),
    )


def estr_publication_evidence(observation: date) -> EcbPublicationEvidence:
    publication_day = _next_target2_business_day(observation + timedelta(days=1))
    lower = datetime.combine(publication_day, time(8, 0), tzinfo=BRUSSELS_ZONE)
    upper = datetime.combine(publication_day, time(9, 0), tzinfo=BRUSSELS_ZONE)
    effective = datetime.combine(observation, time(0, 0), tzinfo=BRUSSELS_ZONE)
    return EcbPublicationEvidence(
        observation_date=observation,
        actual_publication_timestamp=None,
        publication_lower_bound=lower,
        publication_upper_bound=upper,
        publication_upper_bound_exclusive=False,
        publication_evidence_kind=PublicationEvidenceKind.BOUNDED_TIME_ENVELOPE.value,
        publication_evidence_source="ECB_ESTR_T_PLUS_1_08_00_TO_09_00_REVISION_WINDOW",
        effective_timestamp=effective,
        strategy_availability_timestamp=max(upper, effective),
    )


def _next_target2_business_day(day: date) -> date:
    calendar = calendar_definition(TARGET2)
    candidate = day
    while not calendar.is_open(candidate):
        candidate += timedelta(days=1)
    return candidate


def _strict_sdmx_csv_rows(
    snapshot: SourceSnapshot,
    *,
    required_fields: tuple[str, ...],
) -> tuple[Mapping[str, object], ...]:
    content_type = snapshot.content_type.partition(";")[0].strip().lower()
    if content_type not in {"text/csv", "application/csv"}:
        raise RateSourceError("ECB_SDMX_UNEXPECTED_CONTENT_TYPE")
    try:
        text = snapshot.payload.decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(text), strict=True)
        if tuple(reader.fieldnames or ()) != required_fields:
            raise RateSourceError("ECB_SDMX_CSV_SCHEMA_CHANGED")
        rows = tuple(dict(row) for row in reader)
    except (UnicodeDecodeError, csv.Error) as exc:
        raise RateSourceError("INVALID_ECB_SDMX_CSV") from exc
    return rows


def required_sdmx_text(row: Mapping[str, object], field_name: str) -> str:
    value = row.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise RateSourceError(f"ECB_{field_name}_REQUIRED")
    return value


def _decimal_percent_to_float(value: object) -> float:
    if not isinstance(value, str) or not value.strip():
        raise RateSourceError("ECB_OBS_VALUE_REQUIRED")
    try:
        result = Decimal(value) / Decimal("100")
    except InvalidOperation as exc:
        raise RateSourceError("INVALID_ECB_OBS_VALUE") from exc
    parsed = float(result)
    if not math.isfinite(parsed):
        raise RateSourceError("NON_FINITE_ECB_RATE")
    return parsed


def _source_document_id(snapshot: SourceSnapshot) -> str:
    record = {
        "endpoint": snapshot.request.url,
        "request_identity": snapshot.request.request_identity,
        "snapshot_sha256": snapshot.source_snapshot_sha256,
    }
    encoded = json.dumps(record, sort_keys=True, separators=(",", ":")).encode()
    return f"ECB_EONIA_ESTR:{hashlib.sha256(encoded).hexdigest()}"
