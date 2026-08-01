"""Federal Reserve Bank of New York EFFR adapter."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from fx_smc_bot.research.publication_censoring import (
    MODERN_EFFR_START,
    PublicationEvidenceKind,
    RevisionStatus,
    legacy_effr_publication_evidence,
    modern_effr_publication_evidence,
)
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

LEGACY_SCHEMA_FINGERPRINT = (
    "da2935b38af012e67bf97d5900d44c64a9495b454262c698ae8827464cf7d00e"
)
MODERN_SCHEMA_FINGERPRINT = (
    "a002a5c557f22d51e9ac2171b981472589800ffe8a03d481629bd8844c165dff"
)
_LEGACY_FIELDS = frozenset(
    {
        "effectiveDate",
        "intraDayHigh",
        "intraDayLow",
        "percentRate",
        "revisionIndicator",
        "stdDeviation",
        "targetRateFrom",
        "targetRateTo",
        "type",
    }
)
_MODERN_EFFR_FIELDS = frozenset(
    {
        "effectiveDate",
        "percentPercentile1",
        "percentPercentile25",
        "percentPercentile75",
        "percentPercentile99",
        "percentRate",
        "revisionIndicator",
        "targetRateFrom",
        "targetRateTo",
        "type",
    }
)
_MODERN_OBFR_FIELDS = _MODERN_EFFR_FIELDS - {"targetRateFrom", "targetRateTo"}
_PREDECESSOR_SNAPSHOTS = {
    "6c0fe53d4d94105dc8e4b12cdd7a709c42715cf4a51be3c297584b61dc005e38": (
        "c2da958e75b10e28d901a197eac1be78b2acdf4ffe77335f0bf325edc68370c3"
    ),
    "a1289ce5201a55ea5c1d28d8df88241dd0be2e0587e3c3e9e1b1cb1bea6a7b4e": (
        "8cf63f8ae7886e63475d8a92cdecac6f5e40d50908498c5eb547f1801cafa342"
    ),
}


@dataclass(frozen=True, slots=True)
class EffrResponseShapeCertification:
    snapshot_sha256: str
    request_identity: str
    schema_fingerprint: str
    inspector_id: str
    row_container_path: str
    schema_role: str
    row_count: int


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
        reasons = []
        if version.publication_timestamp is None:
            reasons.append("EFFR_V1_V2_EXACT_PUBLICATION_REQUIRED")
        else:
            local = version.publication_timestamp.astimezone(
                ZoneInfo("America/New_York")
            )
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


class NewYorkFedEffrAdapterV2(NewYorkFedEffrAdapter):
    """Future-baseline EFFR adapter pinned to the bounded official API."""

    adapter_id = "NY_FED_EFFR_V2"
    parser_version = "NY_FED_EFFR_JSON_V2"
    schema_id = "NY_FED_RATES_SEARCH_JSON_V2"
    endpoint_declarations = (
        OfficialNumericalEndpoint(
            allowlist_identity="F0RPE2ER_OFFICIAL_SOURCE_ALLOWLIST_V1",
            adapter_id=adapter_id,
            currency=NewYorkFedEffrAdapter.currency,
            series_id=NewYorkFedEffrAdapter.series_id,
            publisher=NewYorkFedEffrAdapter.publisher,
            url="https://markets.newyorkfed.org/api/rates/all/search.json",
            start_parameter="startDate",
            end_parameter="endDate",
            series_parameter="eventCodes",
            series_parameter_value="500",
            response_format="JSON",
            accept_media_type="application/json",
            format_parameter="format",
            format_parameter_value="json",
            series_path_token=None,
            format_path_token=None,
            schema_id=schema_id,
            required_fields=tuple(sorted(NewYorkFedEffrAdapter.required_fields)),
            schema_fingerprint=schema_fingerprint(
                schema_id, NewYorkFedEffrAdapter.required_fields
            ),
            publication_timestamp_field="publicationTimestamp",
            effective_timestamp_field="effectiveTimestamp",
        ),
    )

    def build_requests(
        self, start: date, end: date, authorization: RateAccessAuthorization
    ) -> tuple[OfficialRateRequest, ...]:
        declaration = self.endpoint_declarations[0]
        return (
            make_v2_request(
                declaration=declaration,
                endpoint_role=self.endpoint_role,
                start=start,
                end=end,
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
        validate_v2_snapshot(
            snapshot, adapter_id=self.adapter_id, declarations=self.endpoint_declarations
        )
        return super().parse_snapshot(snapshot)


class NewYorkFedEffrAdapterV3(NewYorkFedEffrAdapterV2):
    """Publication-safe EFFR adapter for two exact live response schemas."""

    adapter_id = "NY_FED_EFFR_V3"
    parser_version = "NY_FED_EFFR_JSON_V3_INTERVAL_CENSORED"
    schema_id = "NY_FED_RATES_SEARCH_JSON_V3_INTERVAL_CENSORED"
    endpoint_declarations = (
        OfficialNumericalEndpoint(
            allowlist_identity="F0RPE2ER_OFFICIAL_SOURCE_ALLOWLIST_V1",
            adapter_id=adapter_id,
            currency=NewYorkFedEffrAdapter.currency,
            series_id=NewYorkFedEffrAdapter.series_id,
            publisher=NewYorkFedEffrAdapter.publisher,
            url="https://markets.newyorkfed.org/api/rates/all/search.json",
            start_parameter="startDate",
            end_parameter="endDate",
            series_parameter="eventCodes",
            series_parameter_value="500",
            response_format="JSON",
            accept_media_type="application/json",
            format_parameter="format",
            format_parameter_value="json",
            series_path_token=None,
            format_path_token=None,
            schema_id=schema_id,
            required_fields=tuple(
                sorted({"effectiveDate", "percentRate", "revisionIndicator", "type"})
            ),
            schema_fingerprint=schema_fingerprint(
                schema_id,
                frozenset({"effectiveDate", "percentRate", "revisionIndicator", "type"}),
            ),
            publication_timestamp_field="NOT_PRESENT_DERIVED_BY_FROZEN_OVERLAY",
            effective_timestamp_field="NOT_PRESENT_DERIVED_BY_FROZEN_OVERLAY",
        ),
    )

    def build_requests(
        self, start: date, end: date, authorization: RateAccessAuthorization
    ) -> tuple[OfficialRateRequest, ...]:
        windows: tuple[tuple[date, date], ...]
        if start < MODERN_EFFR_START <= end:
            windows = (
                (start, MODERN_EFFR_START.fromordinal(MODERN_EFFR_START.toordinal() - 1)),
                (MODERN_EFFR_START, end),
            )
        else:
            windows = ((start, end),)
        declaration = self.endpoint_declarations[0]
        return tuple(
            make_v2_request(
                declaration=declaration,
                endpoint_role=self.endpoint_role,
                start=window_start,
                end=window_end,
                query_parameters={
                    "endDate": window_end.isoformat(),
                    "eventCodes": "500",
                    "format": "json",
                    "startDate": window_start.isoformat(),
                    "type": "rate",
                },
                authorization=authorization,
            )
            for window_start, window_end in windows
        )

    def certify_snapshot_shape(
        self, snapshot: SourceSnapshot
    ) -> EffrResponseShapeCertification:
        from fx_smc_bot.research.official_response_shape import (
            INSPECTOR_ID,
            inspect_official_json_response,
        )

        self._validate_v3_or_predecessor_snapshot(snapshot)
        request = snapshot.request
        declaration = request.endpoint_declaration
        if declaration is None:
            raise RateSourceError("EFFR_V3_ENDPOINT_DECLARATION_REQUIRED")
        authorization = RateAccessAuthorization(
            authorization_id=f"EFFR_V3_SHAPE_{request.request_identity}",
            adapter_ids=frozenset({request.adapter_id}),
            currencies=frozenset({request.currency}),
            series_ids=frozenset({request.series_id}),
            start=request.start,
            end=request.end,
            official_hosts=frozenset({urlparse(request.url).hostname or ""}),
            source_allowlist_identities=frozenset({declaration.allowlist_identity}),
        )
        shape = inspect_official_json_response(snapshot, authorization)
        fingerprint = shape.schema_fingerprint
        if fingerprint == LEGACY_SCHEMA_FINGERPRINT:
            role = "LEGACY_PRE_FIELD_CHANGE_SCHEMA"
            if request.end >= MODERN_EFFR_START:
                raise RateSourceError("LEGACY_SCHEMA_OUTSIDE_FROZEN_DATE_REGIME")
        elif fingerprint == MODERN_SCHEMA_FINGERPRINT:
            role = "MODERN_POST_FIELD_CHANGE_SCHEMA"
            if request.start < MODERN_EFFR_START:
                raise RateSourceError("MODERN_SCHEMA_OUTSIDE_FROZEN_DATE_REGIME")
        else:
            raise RateSourceError("UNKNOWN_EFFR_SCHEMA_FINGERPRINT")
        if shape.candidate_row_container_paths != ("$.refRates",):
            raise RateSourceError("EFFR_ROW_CONTAINER_PATH_MISMATCH")
        return EffrResponseShapeCertification(
            snapshot_sha256=snapshot.source_snapshot_sha256,
            request_identity=request.request_identity,
            schema_fingerprint=fingerprint,
            inspector_id=INSPECTOR_ID,
            row_container_path="$.refRates",
            schema_role=role,
            row_count=shape.row_count,
        )

    def parse_snapshot(self, snapshot: SourceSnapshot) -> tuple[RateVersion, ...]:
        certification = self.certify_snapshot_shape(snapshot)
        try:
            document = json.loads(snapshot.payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RateSourceError("INVALID_EFFR_V3_JSON") from exc
        if not isinstance(document, dict) or set(document) != {"refRates"}:
            raise RateSourceError("EFFR_V3_TOP_LEVEL_SCHEMA_CHANGED")
        raw_rows = document["refRates"]
        if not isinstance(raw_rows, list):
            raise RateSourceError("EFFR_V3_ROWS_REQUIRED")

        selected: dict[date, RateVersion] = {}
        for ordinal, raw_row in enumerate(raw_rows):
            if not isinstance(raw_row, dict):
                raise RateSourceError("EFFR_V3_ROW_OBJECT_REQUIRED")
            row = raw_row
            row_type = row.get("type")
            if not isinstance(row_type, str):
                raise RateSourceError("EFFR_V3_ROW_TYPE_REQUIRED")
            self._validate_v3_row_fields(
                row,
                row_type=row_type,
                schema_fingerprint=certification.schema_fingerprint,
            )
            observation = parse_date(row.get("effectiveDate"))
            if observation < snapshot.request.start or observation > snapshot.request.end:
                raise RateSourceError("EFFR_OBSERVATION_OUTSIDE_REQUEST_WINDOW")
            if row_type == "OBFR":
                continue
            if row_type != "EFFR":
                raise RateSourceError("UNEXPECTED_NY_FED_SERIES_TYPE")
            version = self._version_from_effr_row(
                snapshot,
                row,
                observation=observation,
                source_row_ordinal=ordinal,
                schema_fingerprint=certification.schema_fingerprint,
            )
            previous = selected.get(observation)
            if previous is not None:
                if self._semantic_version_record(previous) != self._semantic_version_record(
                    version
                ):
                    raise RateSourceError("CONFLICTING_FINAL_HISTORY_EFFR_ROWS")
                continue
            selected[observation] = version
        if not selected:
            raise RateSourceError("EFFR_ROWS_REQUIRED")
        return tuple(selected[key] for key in sorted(selected))

    def certify_version(self, version: RateVersion) -> RateCertification:
        reasons: list[str] = []
        expected_evidence = (
            legacy_effr_publication_evidence(version.observation_date)
            if version.observation_date < MODERN_EFFR_START
            else modern_effr_publication_evidence(version.observation_date)
        )
        expected_fingerprint = (
            LEGACY_SCHEMA_FINGERPRINT
            if version.observation_date < MODERN_EFFR_START
            else MODERN_SCHEMA_FINGERPRINT
        )
        expected_kind = (
            PublicationEvidenceKind.PUBLICATION_DAY_ENVELOPE.value
            if version.observation_date < MODERN_EFFR_START
            else PublicationEvidenceKind.BOUNDED_TIME_ENVELOPE.value
        )
        if version.currency != "USD" or version.series_id != "EFFR":
            reasons.append("IDENTITY_MISMATCH")
        if version.source_publisher != self.publisher:
            reasons.append("PUBLISHER_MISMATCH")
        if version.parser_version != self.parser_version:
            reasons.append("PARSER_VERSION_MISMATCH")
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
        if version.publication_timestamp is not None:
            reasons.append("CENSORED_PUBLICATION_MUST_NOT_CLAIM_ACTUAL_TIMESTAMP")
        if version.revision_identifier is not None or version.revision_status != (
            RevisionStatus.FINAL_HISTORY_ONLY_NO_EXPLICIT_REVISION_ID.value
        ):
            reasons.append("FINAL_HISTORY_REVISION_SEMANTICS_MISMATCH")
        if version.calendar_id != "NEW_YORK_FED_BUSINESS_DAY":
            reasons.append("CALENDAR_MISMATCH")
        return RateCertification(
            adapter_id=self.adapter_id,
            identity=version.identity,
            revision_identifier=version.revision_identifier,
            passed=not reasons,
            status="PASS" if not reasons else "BLOCKED_BY_USD_ADAPTER_V3",
            checks=(
                "SCHEMA_FINGERPRINT",
                "SERIES_IDENTITY",
                "UNIT_CONVERSION",
                "PUBLICATION_BOUNDS",
                "STRATEGY_AVAILABILITY",
                "REVISION_NULLABILITY",
                "CALENDAR",
            ),
            reasons=tuple(reasons),
        )

    def _validate_v3_or_predecessor_snapshot(self, snapshot: SourceSnapshot) -> None:
        request = snapshot.request
        if request.adapter_id == self.adapter_id:
            validate_v2_snapshot(
                snapshot,
                adapter_id=self.adapter_id,
                declarations=self.endpoint_declarations,
            )
            return
        if request.adapter_id != NewYorkFedEffrAdapterV2.adapter_id:
            raise RateSourceError("EFFR_V3_SNAPSHOT_ADAPTER_MISMATCH")
        validate_v2_snapshot(
            snapshot,
            adapter_id=NewYorkFedEffrAdapterV2.adapter_id,
            declarations=NewYorkFedEffrAdapterV2.endpoint_declarations,
        )
        expected_snapshot = _PREDECESSOR_SNAPSHOTS.get(request.request_identity)
        if expected_snapshot != snapshot.source_snapshot_sha256:
            raise RateSourceError("PREDECESSOR_EFFR_SNAPSHOT_IDENTITY_MISMATCH")

    @staticmethod
    def _validate_v3_row_fields(
        row: Mapping[str, object],
        *,
        row_type: str,
        schema_fingerprint: str,
    ) -> None:
        keys = frozenset(row)
        if schema_fingerprint == LEGACY_SCHEMA_FINGERPRINT:
            if row_type != "EFFR" or keys != _LEGACY_FIELDS:
                raise RateSourceError("LEGACY_EFFR_ROW_SCHEMA_CHANGED")
        elif row_type == "EFFR":
            if keys != _MODERN_EFFR_FIELDS:
                raise RateSourceError("MODERN_EFFR_ROW_SCHEMA_CHANGED")
        elif row_type == "OBFR":
            if keys != _MODERN_OBFR_FIELDS:
                raise RateSourceError("MODERN_OBFR_ROW_SCHEMA_CHANGED")
        else:
            raise RateSourceError("UNEXPECTED_NY_FED_SERIES_TYPE")
        if not isinstance(row.get("revisionIndicator"), str):
            raise RateSourceError("EFFR_REVISION_INDICATOR_REQUIRED")

    def _version_from_effr_row(
        self,
        snapshot: SourceSnapshot,
        row: Mapping[str, object],
        *,
        observation: date,
        source_row_ordinal: int,
        schema_fingerprint: str,
    ) -> RateVersion:
        raw_rate = row.get("percentRate")
        if isinstance(raw_rate, bool) or not isinstance(raw_rate, int | float):
            raise RateSourceError("EFFR_PERCENT_RATE_NUMERIC_REQUIRED")
        try:
            decimal_rate = Decimal(str(raw_rate)) / Decimal("100")
        except InvalidOperation as exc:
            raise RateSourceError("INVALID_EFFR_PERCENT_RATE") from exc
        value = float(decimal_rate)
        if not math.isfinite(value):
            raise RateSourceError("NON_FINITE_EFFR_RATE")
        evidence = (
            legacy_effr_publication_evidence(observation)
            if observation < MODERN_EFFR_START
            else modern_effr_publication_evidence(observation)
        )
        source_document_id = self._source_document_id(snapshot)
        metadata = tuple(
            sorted(
                (key, str(value))
                for key, value in row.items()
                if key
                not in {
                    "effectiveDate",
                    "percentRate",
                    "type",
                }
            )
        )
        return RateVersion(
            currency=self.currency,
            series_id=self.series_id,
            observation_date=observation,
            value=value,
            publication_timestamp=None,
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
            calendar_id="NEW_YORK_FED_BUSINESS_DAY",
            retrieved_at=snapshot.retrieved_at,
            source_metadata=metadata,
            publication_lower_bound=evidence.publication_lower_bound,
            publication_upper_bound=evidence.publication_upper_bound,
            publication_upper_bound_exclusive=(
                evidence.publication_upper_bound_exclusive
            ),
            publication_evidence_kind=evidence.publication_evidence_kind.value,
            publication_evidence_source=evidence.publication_evidence_source,
            schema_fingerprint=schema_fingerprint,
            source_row_ordinal=source_row_ordinal,
            source_adapter_id=snapshot.request.adapter_id,
            source_request_identity=snapshot.request.request_identity,
        )

    @staticmethod
    def _source_document_id(snapshot: SourceSnapshot) -> str:
        record = {
            "endpoint": snapshot.request.url,
            "request_identity": snapshot.request.request_identity,
            "snapshot_sha256": snapshot.source_snapshot_sha256,
        }
        encoded = json.dumps(record, sort_keys=True, separators=(",", ":")).encode()
        return f"NY_FED_EFFR:{hashlib.sha256(encoded).hexdigest()}"

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
