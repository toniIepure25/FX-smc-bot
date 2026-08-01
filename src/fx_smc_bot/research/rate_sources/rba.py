"""Reserve Bank of Australia official cash-rate adapter."""

from __future__ import annotations

import hashlib
import json
import math
import struct
import xml.etree.ElementTree as ET
import zipfile
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from io import BytesIO
from zoneinfo import ZoneInfo

from fx_smc_bot.research.publication_censoring import (
    PublicationEvidenceKind,
    RevisionStatus,
    first_portfolio_execution_strictly_after,
)
from fx_smc_bot.research.rate_calendars import RITS_BUSINESS_DAY, calendar_definition
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

RBA_F1_HISTORICAL_URL = "https://www.rba.gov.au/statistics/tables/xls-hist/f01dhist.xls"
RBA_F1_CURRENT_URL = "https://www.rba.gov.au/statistics/tables/xls/f01d.xlsx"
RBA_F1_HISTORICAL_SCHEMA_FINGERPRINT = (
    "fce982bc4adbf9c3f5b1588780320b78be96b38b155e0981a1a1de9e9cfff65a"
)
RBA_F1_CURRENT_SCHEMA_FINGERPRINT = (
    "abcaf1b6d80a76d816fd580b6b74a88080054a4c69d5ffbbf568345fc4f5b492"
)
RBA_F1_SHAPE_INSPECTOR_ID = "F0RPE2ERUSDSRLPAEURSRGBPSRAUDSR_RBA_F1_SHAPE_V1"
RBA_F1_RECONCILIATION_ID = "RBA_F1_CASH_RATE_SCHEMA_RECONCILIATION_V1"
RBA_CURRENT_AUTHORIZED_START = date(2011, 1, 4)
RBA_AUTHORIZED_END = date(2022, 12, 31)
RBA_HISTORICAL_AUTHORIZED_END = date(2010, 12, 31)
RBA_SYDNEY_ZONE = ZoneInfo("Australia/Sydney")


@dataclass(frozen=True, slots=True)
class RbaF1ShapeCertification:
    snapshot_sha256: str
    request_identity: str
    schema_fingerprint: str
    inspector_id: str
    row_container_path: str
    schema_role: str
    row_count: int


@dataclass(frozen=True, slots=True)
class RbaPublicationEvidence:
    observation_date: date
    publication_date: date
    actual_publication_timestamp: datetime | None
    publication_lower_bound: datetime
    publication_upper_bound: datetime
    publication_upper_bound_exclusive: bool
    publication_evidence_kind: str
    publication_evidence_source: str
    effective_timestamp: datetime
    strategy_availability_timestamp: datetime


class RbaCashRateAdapter:
    adapter_id = "RBA_CASH_RATE_V1"
    currency = "AUD"
    series_id = "RBA_CASH_RATE"
    parser_version = "RBA_CASH_RATE_JSON_V1"
    publisher = "Reserve Bank of Australia"
    endpoint_role = "official_cash_rate_export"
    schema_id = "rba-cash-rate-official-v1"
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
                url="https://www.rba.gov.au/statistics/cash-rate/cash-rate.json",
                query_parameters={"end-date": end.isoformat(), "start-date": start.isoformat()},
                authorization=authorization,
            ),
        )

    def parse_snapshot(self, snapshot: SourceSnapshot) -> tuple[RateVersion, ...]:
        self._validate_snapshot(snapshot)
        rows = strict_json_rows(
            snapshot, schema_id=self.schema_id, required_row_fields=self.required_fields
        )
        return reject_duplicate_versions(
            tuple(
                version_from_row(
                    snapshot,
                    row,
                    currency=self.currency,
                    expected_series_id=self.series_id,
                    publisher=self.publisher,
                    parser_version=self.parser_version,
                    day_count_convention="ACT_365_FIXED",
                    calendar_id="RITS_BUSINESS_DAY",
                    metadata_fields=("methodologyRegime",),
                )
                for row in rows
            )
        )

    def certify_version(self, version: RateVersion) -> RateCertification:
        result = certify_common(
            version,
            adapter_id=self.adapter_id,
            currency=self.currency,
            series_ids=frozenset({self.series_id}),
            publisher=self.publisher,
            parser_version=self.parser_version,
            day_count_convention="ACT_365_FIXED",
            calendar_id="RITS_BUSINESS_DAY",
            publication_zone="Australia/Sydney",
            endpoint_roles=frozenset({self.endpoint_role}),
        )
        local = version.strategy_availability_timestamp.astimezone(ZoneInfo("Australia/Sydney"))
        reasons = []
        if local.date() <= version.observation_date or (local.hour, local.minute) < (16, 0):
            reasons.append("RBA_BEFORE_CONSERVATIVE_REVISION_ENVELOPE")
        return combine_certification(result, reasons)

    def _validate_snapshot(self, snapshot: SourceSnapshot) -> None:
        if (
            snapshot.request.adapter_id != self.adapter_id
            or snapshot.request.series_id != self.series_id
        ):
            raise RateSourceError("SNAPSHOT_REQUEST_IDENTITY_MISMATCH")


class RbaCashRateAdapterV2(RbaCashRateAdapter):
    """Future-baseline RBA cash-rate adapter with bounded query identity."""

    adapter_id = "RBA_CASH_RATE_V2"
    parser_version = "RBA_CASH_RATE_JSON_V2"
    schema_id = "RBA_CASH_RATE_JSON_V2"
    endpoint_declarations = (
        OfficialNumericalEndpoint(
            allowlist_identity="F0RPE2ER_OFFICIAL_SOURCE_ALLOWLIST_V1",
            adapter_id=adapter_id,
            currency=RbaCashRateAdapter.currency,
            series_id=RbaCashRateAdapter.series_id,
            publisher=RbaCashRateAdapter.publisher,
            url="https://www.rba.gov.au/statistics/cash-rate/cash-rate.json",
            start_parameter="start-date",
            end_parameter="end-date",
            series_parameter="FIXED_ENDPOINT_SERIES",
            series_parameter_value="RBA_CASH_RATE",
            response_format="JSON",
            accept_media_type="application/json",
            format_parameter=None,
            format_parameter_value=None,
            series_path_token=None,
            format_path_token=".json",
            schema_id=schema_id,
            required_fields=tuple(sorted(RbaCashRateAdapter.required_fields)),
            schema_fingerprint=schema_fingerprint(schema_id, RbaCashRateAdapter.required_fields),
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
                    "end-date": end.isoformat(),
                    "start-date": start.isoformat(),
                },
                authorization=authorization,
            ),
        )

    def parse_snapshot(self, snapshot: SourceSnapshot) -> tuple[RateVersion, ...]:
        validate_v2_snapshot(
            snapshot, adapter_id=self.adapter_id, declarations=self.endpoint_declarations
        )
        return super().parse_snapshot(snapshot)


class RbaCashRateAdapterV3(RbaCashRateAdapter):
    """Official RBA F1 workbook adapter for the actual interbank Cash Rate."""

    adapter_id = "RBA_CASH_RATE_V3"
    parser_version = "RBA_F1_CASH_RATE_WORKBOOK_V3"
    endpoint_role = "official_rba_statistical_table_f1"
    historical_endpoint_role = "official_rba_f1_historical_xls"
    current_endpoint_role = "official_rba_f1_current_xlsx_quarantined"
    schema_id = "RBA_STATISTICAL_TABLE_F1_WORKBOOK_V3"

    def build_requests(
        self, start: date, end: date, authorization: RateAccessAuthorization
    ) -> tuple[OfficialRateRequest, ...]:
        requests: list[OfficialRateRequest] = []
        if start <= RBA_HISTORICAL_AUTHORIZED_END:
            historical_end = min(end, RBA_HISTORICAL_AUTHORIZED_END)
            requests.append(
                self._request(
                    start,
                    historical_end,
                    RBA_F1_HISTORICAL_URL,
                    self.historical_endpoint_role,
                    "application/vnd.ms-excel",
                    authorization,
                )
            )
        if end >= RBA_CURRENT_AUTHORIZED_START:
            current_start = max(start, RBA_CURRENT_AUTHORIZED_START)
            requests.append(
                self._request(
                    current_start,
                    end,
                    RBA_F1_CURRENT_URL,
                    self.current_endpoint_role,
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    authorization,
                )
            )
        if not requests:
            raise RateSourceError("RBA_F1_REQUEST_OUTSIDE_SOURCE_COVERAGE")
        return tuple(requests)

    def certify_snapshot_shape(self, snapshot: SourceSnapshot) -> RbaF1ShapeCertification:
        self._validate_snapshot(snapshot)
        rows, fingerprint, role = _parse_rba_f1_snapshot(snapshot)
        if not rows:
            raise RateSourceError("RBA_F1_ROWS_REQUIRED")
        return RbaF1ShapeCertification(
            snapshot_sha256=snapshot.source_snapshot_sha256,
            request_identity=snapshot.request.request_identity,
            schema_fingerprint=fingerprint,
            inspector_id=RBA_F1_SHAPE_INSPECTOR_ID,
            row_container_path="$.rba_f1_cash_rate_rows",
            schema_role=role,
            row_count=len(rows),
        )

    def parse_snapshot(self, snapshot: SourceSnapshot) -> tuple[RateVersion, ...]:
        certification = self.certify_snapshot_shape(snapshot)
        rows, fingerprint, _role = _parse_rba_f1_snapshot(snapshot)
        if fingerprint != certification.schema_fingerprint:
            raise RateSourceError("RBA_F1_SCHEMA_FINGERPRINT_MISMATCH")
        versions: dict[date, RateVersion] = {}
        for ordinal, row in enumerate(rows):
            version = self._version_from_row(
                snapshot,
                row,
                source_row_ordinal=ordinal,
                schema_fingerprint=fingerprint,
            )
            previous = versions.get(version.observation_date)
            if previous is not None:
                if self._semantic_version_record(previous) != self._semantic_version_record(
                    version
                ):
                    raise RateSourceError("CONFLICTING_FINAL_HISTORY_RBA_CASH_RATE_ROWS")
                continue
            versions[version.observation_date] = version
        return tuple(versions[day] for day in sorted(versions))

    def certify_version(self, version: RateVersion) -> RateCertification:
        reasons: list[str] = []
        if version.currency != self.currency or version.series_id != self.series_id:
            reasons.append("IDENTITY_MISMATCH")
        if version.source_publisher != self.publisher:
            reasons.append("PUBLISHER_MISMATCH")
        if version.parser_version != self.parser_version:
            reasons.append("PARSER_VERSION_MISMATCH")
        if version.schema_fingerprint not in {
            RBA_F1_HISTORICAL_SCHEMA_FINGERPRINT,
            RBA_F1_CURRENT_SCHEMA_FINGERPRINT,
        }:
            reasons.append("SCHEMA_FINGERPRINT_MISMATCH")
        try:
            expected = rba_cash_rate_publication_evidence(version.observation_date)
        except RateSourceError as exc:
            reasons.append(str(exc))
            expected = None
        if expected is not None:
            if version.publication_timestamp != expected.actual_publication_timestamp:
                reasons.append("ACTUAL_PUBLICATION_TIMESTAMP_MISMATCH")
            if (
                version.resolved_publication_lower_bound != expected.publication_lower_bound
                or version.resolved_publication_upper_bound != expected.publication_upper_bound
                or version.publication_upper_bound_exclusive
                != expected.publication_upper_bound_exclusive
                or version.publication_evidence_kind != expected.publication_evidence_kind
                or version.publication_evidence_source != expected.publication_evidence_source
            ):
                reasons.append("PUBLICATION_BOUNDS_MISMATCH")
            if version.effective_timestamp != expected.effective_timestamp:
                reasons.append("EFFECTIVE_TIMESTAMP_MISMATCH")
            if version.strategy_availability_timestamp != expected.strategy_availability_timestamp:
                reasons.append("STRATEGY_AVAILABILITY_MISMATCH")
        if version.revision_identifier is not None or version.revision_status != (
            RevisionStatus.FINAL_HISTORY_ONLY_NO_EXPLICIT_REVISION_ID.value
        ):
            reasons.append("FINAL_HISTORY_REVISION_SEMANTICS_MISMATCH")
        if version.day_count_convention != "ACT_365_FIXED":
            reasons.append("DAY_COUNT_MISMATCH")
        if version.calendar_id != RITS_BUSINESS_DAY:
            reasons.append("CALENDAR_MISMATCH")
        return RateCertification(
            adapter_id=self.adapter_id,
            identity=version.identity,
            revision_identifier=version.revision_identifier,
            passed=not reasons,
            status="PASS" if not reasons else "BLOCKED_BY_OFFICIAL_RATE_ADAPTER",
            checks=(
                "RBA_OFFICIAL_F1_IDENTITY",
                "CASH_RATE_SERIES_IDENTITY",
                "CASH_RATE_TARGET_REJECTION",
                "UNIT_CONVERSION",
                "RITS_CALENDAR",
                "PUBLICATION_DAY_ENVELOPE",
                "REVISION_NULLABILITY",
                "EXPERT_JUDGEMENT_METADATA",
            ),
            reasons=tuple(reasons),
        )

    def _version_from_row(
        self,
        snapshot: SourceSnapshot,
        row: Mapping[str, object],
        *,
        source_row_ordinal: int,
        schema_fingerprint: str,
    ) -> RateVersion:
        observation = _required_day(row, "observation_date")
        if observation < snapshot.request.start or observation > snapshot.request.end:
            raise RateSourceError("RBA_F1_OBSERVATION_OUTSIDE_REQUEST_BOUNDS")
        if observation > RBA_AUTHORIZED_END:
            raise RateSourceError("RBA_F1_OBSERVATION_OUTSIDE_AUTHORIZED_SCOPE")
        if snapshot.request.source_endpoint_role == self.current_endpoint_role and (
            observation < RBA_CURRENT_AUTHORIZED_START
        ):
            raise RateSourceError("RBA_CURRENT_F1_BEFORE_OFFICIAL_START")
        if not _rits_is_open_for_observation(observation):
            raise RateSourceError("RBA_F1_NON_RITS_BUSINESS_DAY_OBSERVATION")
        if str(row.get("series_code")) != "FIRMMCRID":
            raise RateSourceError("RBA_F1_CASH_RATE_SERIES_CODE_MISMATCH")
        value = _decimal_percent_to_float(row.get("cash_rate_percent"))
        evidence = rba_cash_rate_publication_evidence(observation)
        metadata = tuple(
            sorted(
                (str(key), str(value))
                for key, value in row.items()
                if key not in {"cash_rate_percent", "observation_date"} and value not in (None, "")
            )
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
            source_document_id=_source_document_id(snapshot),
            source_endpoint_role=snapshot.request.source_endpoint_role,
            source_snapshot_sha256=snapshot.source_snapshot_sha256,
            parser_version=self.parser_version,
            revision_identifier=None,
            revision_status=RevisionStatus.FINAL_HISTORY_ONLY_NO_EXPLICIT_REVISION_ID.value,
            day_count_convention="ACT_365_FIXED",
            calendar_id=RITS_BUSINESS_DAY,
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

    def _request(
        self,
        start: date,
        end: date,
        url: str,
        endpoint_role: str,
        accept: str,
        authorization: RateAccessAuthorization,
    ) -> OfficialRateRequest:
        request = OfficialRateRequest(
            adapter_id=self.adapter_id,
            currency=self.currency,
            series_id=self.series_id,
            source_publisher=self.publisher,
            source_endpoint_role=endpoint_role,
            start=start,
            end=end,
            url=url,
            query_parameters=(),
            request_headers=(("Accept", accept),),
        )
        authorization.authorize(request)
        return request

    def _validate_snapshot(self, snapshot: SourceSnapshot) -> None:
        if (
            snapshot.request.adapter_id != self.adapter_id
            or snapshot.request.series_id != self.series_id
            or snapshot.request.currency != self.currency
        ):
            raise RateSourceError("SNAPSHOT_REQUEST_IDENTITY_MISMATCH")
        if snapshot.request.source_endpoint_role == self.historical_endpoint_role:
            if snapshot.request.url != RBA_F1_HISTORICAL_URL:
                raise RateSourceError("RBA_HISTORICAL_F1_ENDPOINT_MISMATCH")
        elif snapshot.request.source_endpoint_role == self.current_endpoint_role:
            if snapshot.request.url != RBA_F1_CURRENT_URL:
                raise RateSourceError("RBA_CURRENT_F1_ENDPOINT_MISMATCH")
        else:
            raise RateSourceError("RBA_F1_ENDPOINT_ROLE_MISMATCH")

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


def rba_cash_rate_publication_evidence(observation: date) -> RbaPublicationEvidence:
    publication_day = _next_rits_business_day(observation + timedelta(days=1))
    lower = datetime.combine(publication_day, time.min, tzinfo=RBA_SYDNEY_ZONE)
    upper = datetime.combine(
        publication_day + timedelta(days=1),
        time.min,
        tzinfo=RBA_SYDNEY_ZONE,
    )
    return RbaPublicationEvidence(
        observation_date=observation,
        publication_date=publication_day,
        actual_publication_timestamp=None,
        publication_lower_bound=lower,
        publication_upper_bound=upper,
        publication_upper_bound_exclusive=True,
        publication_evidence_kind=PublicationEvidenceKind.PUBLICATION_DAY_ENVELOPE.value,
        publication_evidence_source="RBA_CASH_RATE_PROCEDURES_MANUAL_PUBLICATION_DAY_ENVELOPE_V1",
        effective_timestamp=lower,
        strategy_availability_timestamp=_first_new_york_execution_after(upper),
    )


def _parse_rba_f1_snapshot(
    snapshot: SourceSnapshot,
) -> tuple[tuple[Mapping[str, object], ...], str, str]:
    if snapshot.request.source_endpoint_role == RbaCashRateAdapterV3.historical_endpoint_role:
        return (
            _parse_historical_xls(snapshot),
            RBA_F1_HISTORICAL_SCHEMA_FINGERPRINT,
            "RBA_F1_HISTORICAL_XLS_FIRMMCRID",
        )
    if snapshot.request.source_endpoint_role == RbaCashRateAdapterV3.current_endpoint_role:
        return (
            _parse_current_xlsx(snapshot),
            RBA_F1_CURRENT_SCHEMA_FINGERPRINT,
            "RBA_F1_CURRENT_XLSX_FIRMMCRID_QUARANTINED",
        )
    raise RateSourceError("RBA_F1_ENDPOINT_ROLE_MISMATCH")


def _parse_current_xlsx(snapshot: SourceSnapshot) -> tuple[Mapping[str, object], ...]:
    media_type = snapshot.content_type.partition(";")[0].strip().lower()
    if media_type not in {
        "application/octet-stream",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/zip",
    }:
        raise RateSourceError("RBA_CURRENT_F1_UNEXPECTED_CONTENT_TYPE")
    try:
        archive = zipfile.ZipFile(BytesIO(snapshot.payload))
    except zipfile.BadZipFile as exc:
        raise RateSourceError("RBA_CURRENT_F1_INVALID_XLSX") from exc
    shared = _xlsx_shared_strings(archive)
    sheet_names = _xlsx_sheet_names(archive)
    if "Data" not in sheet_names or "Notes" not in sheet_names:
        raise RateSourceError("RBA_CURRENT_F1_REQUIRED_SHEETS_MISSING")
    sheet_path = sheet_names["Data"]
    rows: list[Mapping[str, object]] = []
    headers: dict[tuple[int, str], str] = {}
    future_dates_seen = False
    with archive.open(sheet_path) as stream:
        for _event, elem in ET.iterparse(stream, events=("end",)):
            if _strip_ns(elem.tag) != "row":
                continue
            row_index = int(elem.attrib.get("r", "0"))
            cells = list(elem)
            if row_index <= 11:
                for cell in cells:
                    ref = cell.attrib.get("r", "")
                    text = _xlsx_cell_text(cell, shared)
                    if ref and text is not None:
                        headers[(row_index, _cell_column(ref))] = text
                elem.clear()
                continue
            date_cell = next(
                (cell for cell in cells if _cell_column(cell.attrib.get("r", "")) == "A"), None
            )
            observed = _xlsx_date(date_cell, shared) if date_cell is not None else None
            if observed is None:
                elem.clear()
                continue
            if observed > RBA_AUTHORIZED_END:
                future_dates_seen = True
                elem.clear()
                continue
            if observed < snapshot.request.start or observed > snapshot.request.end:
                elem.clear()
                continue
            value_cell = next(
                (cell for cell in cells if _cell_column(cell.attrib.get("r", "")) == "D"), None
            )
            value = _xlsx_numeric(value_cell, shared)
            rows.append(
                {
                    "observation_date": observed,
                    "cash_rate_percent": value,
                    "series_code": "FIRMMCRID",
                    "worksheet": "Data",
                    "date_column": "A",
                    "cash_rate_column": "D",
                    "source_workbook": "f01d.xlsx",
                    "post_2022_dates_structurally_encountered": "False",
                    "expert_judgement_sheet_present": str("Use of Expert Judgement" in sheet_names),
                }
            )
            elem.clear()
    _validate_current_headers(headers)
    if future_dates_seen:
        rows = [
            {
                **row,
                "post_2022_dates_structurally_encountered": "True",
            }
            for row in rows
        ]
    return tuple(rows)


def _parse_historical_xls(snapshot: SourceSnapshot) -> tuple[Mapping[str, object], ...]:
    media_type = snapshot.content_type.partition(";")[0].strip().lower()
    if media_type not in {"application/octet-stream", "application/vnd.ms-excel"}:
        raise RateSourceError("RBA_HISTORICAL_F1_UNEXPECTED_CONTENT_TYPE")
    workbook = _OleWorkbook(snapshot.payload)
    records = workbook.records_for_sheet("Data")
    strings = _biff_shared_strings(workbook.records)
    labels = _biff_label_cells(records, strings)
    _validate_historical_headers(labels)
    dates = _biff_date_cells(records)
    wanted_rows = {
        row: observed
        for row, observed in dates.items()
        if snapshot.request.start <= observed <= snapshot.request.end
    }
    values = _biff_numeric_cells(records, wanted_rows=frozenset(wanted_rows), wanted_col=3)
    rows: list[Mapping[str, object]] = []
    for row in sorted(wanted_rows):
        if row not in values:
            continue
        rows.append(
            {
                "observation_date": wanted_rows[row],
                "cash_rate_percent": values[row],
                "series_code": "FIRMMCRID",
                "worksheet": "Data",
                "date_column": "A",
                "cash_rate_column": "D",
                "source_workbook": "f01dhist.xls",
                "post_2022_dates_structurally_encountered": "False",
                "expert_judgement_sheet_present": "False",
            }
        )
    return tuple(rows)


def _validate_current_headers(headers: Mapping[tuple[int, str], str]) -> None:
    expected = {
        (2, "B"): "Cash Rate Target",
        (2, "D"): "Interbank Overnight Cash Rate",
        (3, "D"): "Interbank Overnight Cash Rate on date",
        (6, "D"): "Per cent",
        (9, "D"): "RBA",
        (11, "D"): "FIRMMCRID",
    }
    for key, value in expected.items():
        if headers.get(key) != value:
            raise RateSourceError("RBA_CURRENT_F1_SCHEMA_CHANGED")
    if headers.get((11, "B")) == "FIRMMCRID":
        raise RateSourceError("RBA_CURRENT_F1_TARGET_COLUMN_SELECTED")


def _validate_historical_headers(labels: Mapping[tuple[int, int], str]) -> None:
    expected = {
        (1, 1): "Cash Rate Target",
        (1, 3): "Interbank Overnight Cash Rate",
        (2, 3): "Interbank Overnight Cash Rate on date",
        (5, 3): "Per cent",
        (8, 3): "RBA",
        (10, 3): "FIRMMCRID",
    }
    for key, value in expected.items():
        if labels.get(key) != value:
            raise RateSourceError("RBA_HISTORICAL_F1_SCHEMA_CHANGED")
    if labels.get((10, 1)) == "FIRMMCRID":
        raise RateSourceError("RBA_HISTORICAL_F1_TARGET_COLUMN_SELECTED")


def _xlsx_shared_strings(archive: zipfile.ZipFile) -> tuple[str, ...]:
    try:
        payload = archive.read("xl/sharedStrings.xml")
    except KeyError:
        return ()
    root = ET.fromstring(payload)
    strings: list[str] = []
    for item in root:
        if _strip_ns(item.tag) != "si":
            continue
        parts = [node.text or "" for node in item.iter() if _strip_ns(node.tag) == "t"]
        strings.append("".join(parts))
    return tuple(strings)


def _xlsx_sheet_names(archive: zipfile.ZipFile) -> dict[str, str]:
    workbook = ET.fromstring(archive.read("xl/workbook.xml"))
    rels = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    rel_targets = {
        rel.attrib["Id"]: rel.attrib["Target"]
        for rel in rels
        if rel.attrib.get("Id") and rel.attrib.get("Target")
    }
    sheets: dict[str, str] = {}
    for sheet in workbook.iter():
        if _strip_ns(sheet.tag) != "sheet":
            continue
        name = sheet.attrib.get("name")
        rel_id = sheet.attrib.get(
            "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
        )
        if name and rel_id in rel_targets:
            target = rel_targets[rel_id]
            sheets[name] = "xl/" + target.lstrip("/")
    return sheets


def _xlsx_cell_text(cell: ET.Element, shared: tuple[str, ...]) -> str | None:
    value_node = next((child for child in cell if _strip_ns(child.tag) == "v"), None)
    if cell.attrib.get("t") == "inlineStr":
        parts = [node.text or "" for node in cell.iter() if _strip_ns(node.tag) == "t"]
        return "".join(parts)
    if value_node is None or value_node.text is None:
        return None
    if cell.attrib.get("t") == "s":
        return shared[int(value_node.text)]
    return value_node.text


def _xlsx_numeric(cell: ET.Element | None, shared: tuple[str, ...]) -> float:
    if cell is None:
        raise RateSourceError("RBA_F1_CASH_RATE_CELL_MISSING")
    text = _xlsx_cell_text(cell, shared)
    return _parse_float(text)


def _xlsx_date(cell: ET.Element, shared: tuple[str, ...]) -> date | None:
    text = _xlsx_cell_text(cell, shared)
    if text is None:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        serial = _parse_float(text)
        if not 20000 <= serial <= 60000:
            return None
        return date(1899, 12, 30) + timedelta(days=int(serial))


def _strip_ns(tag: str) -> str:
    return tag.rsplit("}", maxsplit=1)[-1]


def _cell_column(ref: str) -> str:
    return "".join(ch for ch in ref if ch.isalpha())


def _decimal_percent_to_float(value: object) -> float:
    parsed = _parse_float(value)
    decimal = parsed / 100.0
    if not math.isfinite(decimal) or not -1.0 <= decimal <= 1.0:
        raise RateSourceError("RBA_F1_RATE_OUT_OF_RANGE")
    return decimal


def _parse_float(value: object) -> float:
    try:
        parsed = float(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise RateSourceError("RBA_F1_NUMERIC_VALUE_REQUIRED") from exc
    if not math.isfinite(parsed):
        raise RateSourceError("RBA_F1_NUMERIC_VALUE_REQUIRED")
    return parsed


def _required_day(row: Mapping[str, object], key: str) -> date:
    value = row.get(key)
    if not isinstance(value, date) or isinstance(value, datetime):
        raise RateSourceError(f"{key.upper()}_REQUIRED")
    return value


def _source_document_id(snapshot: SourceSnapshot) -> str:
    return hashlib.sha256(
        json.dumps(
            {
                "url": snapshot.request.url,
                "payload_sha256": snapshot.source_snapshot_sha256,
                "schema": RBA_F1_RECONCILIATION_ID,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("ascii")
    ).hexdigest()


def _rits_is_open_for_observation(day: date) -> bool:
    return calendar_definition(RITS_BUSINESS_DAY).is_open(day)


def _next_rits_business_day(day: date) -> date:
    candidate = day
    while not _rits_publication_day_open(candidate):
        candidate += timedelta(days=1)
    return candidate


def _rits_publication_day_open(day: date) -> bool:
    if day <= RBA_AUTHORIZED_END:
        return calendar_definition(RITS_BUSINESS_DAY).is_open(day)
    if day == date(2023, 1, 2):
        return False
    return day.weekday() < 5


def _first_new_york_execution_after(boundary: datetime) -> datetime:
    if boundary.date() <= RBA_AUTHORIZED_END:
        return first_portfolio_execution_strictly_after(boundary)
    new_york = ZoneInfo("America/New_York")
    local_boundary = boundary.astimezone(new_york)
    candidate_day = local_boundary.date()
    while True:
        if candidate_day.weekday() < 5 and candidate_day not in {
            date(2023, 1, 2),
            date(2023, 12, 25),
        }:
            candidate = datetime.combine(candidate_day, time(17, 5), new_york)
            if candidate > local_boundary:
                return candidate
        candidate_day += timedelta(days=1)


class _OleWorkbook:
    def __init__(self, payload: bytes) -> None:
        if payload[:8] != bytes.fromhex("d0cf11e0a1b11ae1"):
            raise RateSourceError("RBA_HISTORICAL_F1_INVALID_OLE")
        self.payload = payload
        self.sector_size = 1 << struct.unpack_from("<H", payload, 30)[0]
        self.fat = self._read_fat()
        self.entries = self._read_directory()
        workbook = next(
            (entry for entry in self.entries if entry["name"] in {"Workbook", "Book"}),
            None,
        )
        if workbook is None:
            raise RateSourceError("RBA_HISTORICAL_F1_WORKBOOK_STREAM_MISSING")
        self.workbook = self._read_stream(int(workbook["start"]), int(workbook["size"]))
        self.records = self._records(self.workbook)
        self.sheets = self._sheets()

    def records_for_sheet(self, name: str) -> tuple[tuple[int, int, bytes], ...]:
        sheets = sorted(self.sheets, key=lambda item: item["offset"])
        for index, sheet in enumerate(sheets):
            if sheet["name"] != name:
                continue
            start = int(sheet["offset"])
            end = (
                int(sheets[index + 1]["offset"]) if index + 1 < len(sheets) else len(self.workbook)
            )
            return tuple(record for record in self.records if start <= record[0] < end)
        raise RateSourceError("RBA_HISTORICAL_F1_DATA_SHEET_MISSING")

    def _sector(self, sid: int) -> bytes:
        offset = (sid + 1) * self.sector_size
        return self.payload[offset : offset + self.sector_size]

    def _read_fat(self) -> list[int]:
        difat = [struct.unpack_from("<I", self.payload, 76 + i * 4)[0] for i in range(109)]
        fat: list[int] = []
        for sid in difat:
            if sid in {0xFFFFFFFF, 0xFFFFFFFE, 0xFFFFFFFD, 0xFFFFFFFC}:
                continue
            sector = self._sector(sid)
            fat.extend(
                struct.unpack_from("<I", sector, index)[0] for index in range(0, len(sector), 4)
            )
        return fat

    def _chain(self, start: int) -> tuple[int, ...]:
        chain: list[int] = []
        seen: set[int] = set()
        sid = start
        while sid not in {0xFFFFFFFF, 0xFFFFFFFE} and sid < len(self.fat) and sid not in seen:
            seen.add(sid)
            chain.append(sid)
            sid = self.fat[sid]
        return tuple(chain)

    def _read_stream(self, start: int, size: int) -> bytes:
        return b"".join(self._sector(sid) for sid in self._chain(start))[:size]

    def _read_directory(self) -> tuple[Mapping[str, object], ...]:
        first_dir = struct.unpack_from("<I", self.payload, 48)[0]
        directory = self._read_stream(first_dir, 10_000_000)
        entries: list[Mapping[str, object]] = []
        for offset in range(0, len(directory), 128):
            entry = directory[offset : offset + 128]
            if len(entry) < 128:
                break
            name_length = struct.unpack_from("<H", entry, 64)[0]
            if name_length < 2:
                continue
            entries.append(
                {
                    "name": entry[: name_length - 2].decode("utf-16le", "replace"),
                    "type": entry[66],
                    "start": struct.unpack_from("<I", entry, 116)[0],
                    "size": struct.unpack_from("<Q", entry, 120)[0],
                }
            )
        return tuple(entries)

    @staticmethod
    def _records(stream: bytes) -> tuple[tuple[int, int, bytes], ...]:
        records: list[tuple[int, int, bytes]] = []
        offset = 0
        while offset + 4 <= len(stream):
            record_id, length = struct.unpack_from("<HH", stream, offset)
            records.append((offset, record_id, stream[offset + 4 : offset + 4 + length]))
            offset += 4 + length
        return tuple(records)

    def _sheets(self) -> tuple[Mapping[str, object], ...]:
        sheets: list[Mapping[str, object]] = []
        for _offset, record_id, payload in self.records:
            if record_id != 0x0085 or len(payload) < 8:
                continue
            sheet_offset = struct.unpack_from("<I", payload, 0)[0]
            length = payload[6]
            flags = payload[7]
            raw = payload[8 : 8 + length * (2 if flags & 1 else 1)]
            sheets.append(
                {
                    "name": raw.decode("utf-16le" if flags & 1 else "latin1", "replace"),
                    "offset": sheet_offset,
                }
            )
        return tuple(sheets)


def _biff_shared_strings(records: Iterable[tuple[int, int, bytes]]) -> tuple[str, ...]:
    payloads: list[bytes] = []
    record_list = tuple(records)
    for index, (_offset, record_id, payload) in enumerate(record_list):
        if record_id != 0x00FC:
            continue
        payloads.append(payload)
        cursor = index + 1
        while cursor < len(record_list) and record_list[cursor][1] == 0x003C:
            payloads.append(record_list[cursor][2])
            cursor += 1
        break
    if not payloads:
        return ()
    blob = payloads[0][:8] + b"".join([payloads[0][8:], *payloads[1:]])
    strings: list[str] = []
    offset = 8
    while offset + 3 <= len(blob):
        length = struct.unpack_from("<H", blob, offset)[0]
        offset += 2
        flags = blob[offset]
        offset += 1
        rich = flags & 0x08
        extended = flags & 0x04
        wide = flags & 0x01
        rich_count = 0
        extension_size = 0
        if rich:
            rich_count = struct.unpack_from("<H", blob, offset)[0]
            offset += 2
        if extended:
            extension_size = struct.unpack_from("<I", blob, offset)[0]
            offset += 4
        raw_size = length * (2 if wide else 1)
        raw = blob[offset : offset + raw_size]
        offset += raw_size
        strings.append(raw.decode("utf-16le" if wide else "latin1", "replace"))
        offset += rich_count * 4 + extension_size
    return tuple(strings)


def _biff_label_cells(
    records: Iterable[tuple[int, int, bytes]], strings: tuple[str, ...]
) -> dict[tuple[int, int], str]:
    labels: dict[tuple[int, int], str] = {}
    for _offset, record_id, payload in records:
        if record_id != 0x00FD or len(payload) < 10:
            continue
        row, col, _xf, index = struct.unpack_from("<HHHI", payload, 0)
        labels[(row, col)] = strings[index]
    return labels


def _biff_date_cells(records: Iterable[tuple[int, int, bytes]]) -> dict[int, date]:
    serials: dict[int, float] = {}
    for _offset, record_id, payload in records:
        if record_id == 0x0203 and len(payload) >= 14:
            row, col, _xf = struct.unpack_from("<HHH", payload, 0)
            if col == 0:
                serials[row] = struct.unpack_from("<d", payload, 6)[0]
        if record_id == 0x027E and len(payload) >= 10:
            row, col, _xf = struct.unpack_from("<HHH", payload, 0)
            if col == 0:
                serials[row] = _decode_rk(struct.unpack_from("<I", payload, 6)[0])
        elif record_id == 0x00BD and len(payload) >= 8:
            row, first_col = struct.unpack_from("<HH", payload, 0)
            last_col = struct.unpack_from("<H", payload, len(payload) - 2)[0]
            if first_col <= 0 <= last_col:
                raw_offset = 4 + (0 - first_col) * 6 + 2
                serials[row] = _decode_rk(struct.unpack_from("<I", payload, raw_offset)[0])
    base = date(1899, 12, 30)
    return {
        row: base + timedelta(days=int(serial))
        for row, serial in serials.items()
        if 20000 <= serial <= 50000
    }


def _biff_numeric_cells(
    records: Iterable[tuple[int, int, bytes]], *, wanted_rows: frozenset[int], wanted_col: int
) -> dict[int, float]:
    values: dict[int, float] = {}
    for _offset, record_id, payload in records:
        if record_id == 0x027E and len(payload) >= 10:
            row, col, _xf = struct.unpack_from("<HHH", payload, 0)
            if row in wanted_rows and col == wanted_col:
                values[row] = _decode_rk(struct.unpack_from("<I", payload, 6)[0])
        elif record_id == 0x0203 and len(payload) >= 14:
            row, col, _xf = struct.unpack_from("<HHH", payload, 0)
            if row in wanted_rows and col == wanted_col:
                values[row] = struct.unpack_from("<d", payload, 6)[0]
        elif record_id == 0x00BD and len(payload) >= 8:
            row, first_col = struct.unpack_from("<HH", payload, 0)
            last_col = struct.unpack_from("<H", payload, len(payload) - 2)[0]
            if row in wanted_rows and first_col <= wanted_col <= last_col:
                raw_offset = 4 + (wanted_col - first_col) * 6 + 2
                values[row] = _decode_rk(struct.unpack_from("<I", payload, raw_offset)[0])
    return values


def _decode_rk(raw: int) -> float:
    multiplier = raw & 1
    is_integer = raw & 2
    value_bits = raw & 0xFFFFFFFC
    if is_integer:
        value = struct.unpack("<i", struct.pack("<I", value_bits))[0] >> 2
    else:
        value = struct.unpack("<d", struct.pack("<Q", value_bits << 32))[0]
    if multiplier:
        value /= 100.0
    return float(value)
