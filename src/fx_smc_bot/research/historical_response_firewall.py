"""Fail-closed request and response scope firewall for historical rate data.

The firewall deliberately operates before adapter parsing.  A request must first
produce an :class:`ApprovedHistoricalRequest`; only a response associated with
that token can be inspected.  Response rows are accumulated locally and are
returned only after the complete response passes, so callers cannot persist a
valid prefix of an invalid response.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import date
from typing import Final, NoReturn, Protocol, TypeVar, cast

from fx_smc_bot.research.rate_sources.base import (
    OfficialNumericalEndpoint,
    OfficialRateRequest,
    RateSourceError,
    SourceSnapshot,
)

AUTHORIZED_MINIMUM_DATE: Final = date(2010, 1, 1)
AUTHORIZED_MAXIMUM_DATE: Final = date(2022, 12, 31)
AUTHORIZED_CURRENCIES: Final = frozenset({"USD", "EUR", "GBP", "AUD", "JPY", "CAD", "CHF"})
AUTHORIZED_INSTRUMENTS: Final = frozenset(
    {
        "EURUSD",
        "GBPUSD",
        "AUDUSD",
        "USDJPY",
        "USDCAD",
        "USDCHF",
        "EURJPY",
        "GBPJPY",
        "AUDJPY",
    }
)
PROHIBITED_IDENTIFIERS: Final = frozenset({"NZD", "NZDUSD"})
SOURCE_RESPONSE_SCOPE_VIOLATION: Final = "SOURCE_RESPONSE_SCOPE_VIOLATION"
FIREWALL_ID: Final = "F0RPE2ER_HISTORICAL_RESPONSE_FIREWALL_V1"

_T = TypeVar("_T")


@dataclass(frozen=True, slots=True)
class HistoricalResponseContract:
    """Frozen metadata contract for one official machine-readable endpoint."""

    adapter_id: str
    currency: str
    series_ids: frozenset[str]
    schema_id: str
    required_row_fields: frozenset[str]
    allowlist_identity: str
    endpoint_url: str
    minimum_authorized_date: date
    maximum_authorized_date: date
    response_format: str = "json"
    start_parameter: str = "startDate"
    end_parameter: str = "endDate"
    series_parameter: str = "series"
    currency_parameter: str = "currency"
    format_parameter: str = "format"
    observation_date_field: str = "observationDate"
    row_series_field: str = "seriesId"
    row_currency_field: str = "currency"

    def __post_init__(self) -> None:
        if self.currency in PROHIBITED_IDENTIFIERS:
            raise RateSourceError("NZD_RESPONSE_CONTRACT_PROHIBITED")
        if self.currency not in AUTHORIZED_CURRENCIES:
            raise RateSourceError("RESPONSE_CONTRACT_CURRENCY_NOT_AUTHORIZED")
        if (
            not self.adapter_id.strip()
            or not self.schema_id.strip()
            or not self.allowlist_identity.strip()
            or not self.endpoint_url.strip()
        ):
            raise RateSourceError("RESPONSE_CONTRACT_IDENTITY_REQUIRED")
        if (
            self.minimum_authorized_date < AUTHORIZED_MINIMUM_DATE
            or self.maximum_authorized_date > AUTHORIZED_MAXIMUM_DATE
            or self.minimum_authorized_date > self.maximum_authorized_date
        ):
            raise RateSourceError("ALLOWLIST_DATE_BOUNDS_NOT_AUTHORIZED")
        if not self.series_ids or any(not item.strip() for item in self.series_ids):
            raise RateSourceError("RESPONSE_CONTRACT_SERIES_REQUIRED")
        if self.series_ids & PROHIBITED_IDENTIFIERS:
            raise RateSourceError("NZD_RESPONSE_CONTRACT_PROHIBITED")
        identity_fields = {
            self.observation_date_field,
            self.row_series_field,
            self.row_currency_field,
        }
        if not identity_fields <= self.required_row_fields:
            raise RateSourceError("RESPONSE_CONTRACT_IDENTITY_FIELDS_REQUIRED")
        parameter_names = (
            self.start_parameter,
            self.end_parameter,
            self.series_parameter,
            self.currency_parameter,
            self.format_parameter,
        )
        if any(not item.strip() for item in parameter_names) or len(set(parameter_names)) != 5:
            raise RateSourceError("RESPONSE_CONTRACT_PARAMETERS_INVALID")
        if not self.response_format.strip():
            raise RateSourceError("RESPONSE_FORMAT_REQUIRED")

    @property
    def fingerprint(self) -> str:
        record = {
            "adapter_id": self.adapter_id,
            "allowlist_identity": self.allowlist_identity,
            "currency": self.currency,
            "end_parameter": self.end_parameter,
            "format_parameter": self.format_parameter,
            "endpoint_url": self.endpoint_url,
            "maximum_authorized_date": self.maximum_authorized_date.isoformat(),
            "minimum_authorized_date": self.minimum_authorized_date.isoformat(),
            "observation_date_field": self.observation_date_field,
            "required_row_fields": sorted(self.required_row_fields),
            "response_format": self.response_format,
            "row_currency_field": self.row_currency_field,
            "row_series_field": self.row_series_field,
            "schema_id": self.schema_id,
            "series_ids": sorted(self.series_ids),
            "series_parameter": self.series_parameter,
            "start_parameter": self.start_parameter,
            "currency_parameter": self.currency_parameter,
        }
        payload = json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        return hashlib.sha256(payload.encode("ascii")).hexdigest()


@dataclass(frozen=True, slots=True)
class FirewallViolationRecord:
    """Sanitized audit record that cannot contain an observation value."""

    code: str
    stage: str
    request_identity: str
    allowlist_identity: str
    adapter_id: str
    currency: str
    series_id: str
    schema_id: str
    request_start: str
    request_end: str
    offending_date_label: str | None = None
    field_names: tuple[str, ...] = ()
    disposition: str = "RESPONSE_REJECTED_ATOMICALLY_BEFORE_PERSISTENCE"


class FirewallAuditSink(Protocol):
    def record(self, violation: FirewallViolationRecord) -> None: ...


class HistoricalResponseFirewallError(RateSourceError):
    """Failure carrying only a sanitized audit record."""

    def __init__(self, violation: FirewallViolationRecord) -> None:
        self.violation = violation
        super().__init__(violation.code)


@dataclass(frozen=True, slots=True)
class ApprovedHistoricalRequest:
    """Proof that request scope was validated before an acquisition callback."""

    request: OfficialRateRequest
    contract_fingerprint: str
    instrument_scope: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CertifiedHistoricalResponse:
    """An all-or-nothing response accepted by the historical firewall."""

    request_identity: str
    schema_id: str
    rows: tuple[Mapping[str, object], ...]


class HistoricalResponseFirewall:
    """Validate request bounds and atomically certify structured responses."""

    def __init__(
        self,
        contract: HistoricalResponseContract,
        *,
        audit_sink: FirewallAuditSink | None = None,
    ) -> None:
        self.firewall_id = FIREWALL_ID
        self.contract = contract
        self._audit_sink = audit_sink
        self._violations: list[FirewallViolationRecord] = []
        self._certified_response_count = 0
        self._quarantined_response_count = 0
        self._transport_approvals: dict[str, ApprovedHistoricalRequest] = {}
        self._certified_snapshot_sha256s: set[str] = set()

    @classmethod
    def from_endpoint_declaration(
        cls,
        declaration: OfficialNumericalEndpoint,
        *,
        audit_sink: FirewallAuditSink | None = None,
    ) -> HistoricalResponseFirewall:
        """Bind the firewall to one frozen official endpoint declaration."""

        return cls(
            HistoricalResponseContract(
                adapter_id=declaration.adapter_id,
                currency=declaration.currency,
                series_ids=frozenset({declaration.series_id}),
                schema_id=declaration.schema_id,
                required_row_fields=frozenset(declaration.required_fields),
                allowlist_identity=declaration.allowlist_identity,
                endpoint_url=declaration.url,
                minimum_authorized_date=AUTHORIZED_MINIMUM_DATE,
                maximum_authorized_date=AUTHORIZED_MAXIMUM_DATE,
                response_format=declaration.response_format,
                start_parameter=declaration.start_parameter,
                end_parameter=declaration.end_parameter,
                series_parameter=declaration.series_parameter,
                currency_parameter="DECLARED_REQUEST_CURRENCY",
                format_parameter=declaration.format_parameter or "DECLARED_ACCEPT_FORMAT",
            ),
            audit_sink=audit_sink,
        )

    @property
    def violations(self) -> tuple[FirewallViolationRecord, ...]:
        return tuple(self._violations)

    @property
    def certified_response_count(self) -> int:
        return self._certified_response_count

    @property
    def quarantined_response_count(self) -> int:
        return self._quarantined_response_count

    @property
    def certified_snapshot_sha256s(self) -> frozenset[str]:
        return frozenset(self._certified_snapshot_sha256s)

    def validate_request(self, request: OfficialRateRequest) -> None:
        """RateResponseFirewall pre-I/O hook used by the snapshot client."""

        approved = self.preflight(request)
        self._transport_approvals[request.request_identity] = approved

    def validate_snapshot(self, snapshot: SourceSnapshot) -> None:
        """RateResponseFirewall post-I/O hook, before return or persistence."""

        request = snapshot.request
        request_identity = request.request_identity
        approved = self._transport_approvals.pop(request_identity, None)
        if approved is None or approved.request != request:
            self._reject("REQUEST_PREFLIGHT_TOKEN_REQUIRED", "RESPONSE_FIREWALL", request)
        document = self._decode_snapshot(snapshot)
        self.validate_response(approved, document)
        self._certified_snapshot_sha256s.add(snapshot.source_snapshot_sha256)

    def preflight(
        self,
        request: OfficialRateRequest,
        *,
        instruments: Iterable[str] = (),
    ) -> ApprovedHistoricalRequest:
        """Validate all request declarations before any network operation."""

        instrument_scope = tuple(sorted(set(instruments)))
        self.validate_instrument_scope(instrument_scope, request=request)
        if request.adapter_id != self.contract.adapter_id:
            self._reject("REQUEST_ADAPTER_NOT_AUTHORIZED", "REQUEST_PREFLIGHT", request)
        if request.url != self.contract.endpoint_url:
            self._reject("REQUEST_ENDPOINT_NOT_ALLOWLISTED", "REQUEST_PREFLIGHT", request)
        declaration = request.endpoint_declaration
        if declaration is not None and (
            getattr(declaration, "allowlist_identity", None) != self.contract.allowlist_identity
        ):
            self._reject("REQUEST_ALLOWLIST_IDENTITY_MISMATCH", "REQUEST_PREFLIGHT", request)
        if request.currency in PROHIBITED_IDENTIFIERS:
            self._reject("NZD_REQUEST_PROHIBITED", "REQUEST_PREFLIGHT", request)
        if request.currency != self.contract.currency:
            self._reject("REQUEST_CURRENCY_NOT_AUTHORIZED", "REQUEST_PREFLIGHT", request)
        if request.series_id in PROHIBITED_IDENTIFIERS:
            self._reject("NZD_REQUEST_PROHIBITED", "REQUEST_PREFLIGHT", request)
        if request.series_id not in self.contract.series_ids:
            self._reject("REQUEST_SERIES_NOT_AUTHORIZED", "REQUEST_PREFLIGHT", request)
        if (
            request.start < self.contract.minimum_authorized_date
            or request.end > self.contract.maximum_authorized_date
        ):
            self._reject("REQUEST_HISTORICAL_SCOPE_VIOLATION", "REQUEST_PREFLIGHT", request)

        if declaration is not None:
            try:
                declaration.validate_request(request)
            except RateSourceError:
                self._reject(
                    "REQUEST_EXPLICIT_DECLARATION_MISMATCH",
                    "REQUEST_PREFLIGHT",
                    request,
                )
        else:
            parameters = dict(request.query_parameters)
            expected = {
                self.contract.start_parameter: request.start.isoformat(),
                self.contract.end_parameter: request.end.isoformat(),
                self.contract.series_parameter: request.series_id,
                self.contract.currency_parameter: request.currency,
                self.contract.format_parameter: self.contract.response_format,
            }
            if (
                self.contract.start_parameter not in parameters
                or self.contract.end_parameter not in parameters
            ):
                self._reject("REQUEST_SERVER_DATE_BOUNDS_REQUIRED", "REQUEST_PREFLIGHT", request)
            for name, value in expected.items():
                if parameters.get(name) != value:
                    self._reject(
                        "REQUEST_EXPLICIT_DECLARATION_MISMATCH",
                        "REQUEST_PREFLIGHT",
                        request,
                        field_names=(name,),
                    )
        return ApprovedHistoricalRequest(request, self.contract.fingerprint, instrument_scope)

    def execute_after_preflight(
        self,
        request: OfficialRateRequest,
        operation: Callable[[OfficialRateRequest], _T],
        *,
        instruments: Iterable[str] = (),
    ) -> tuple[ApprovedHistoricalRequest, _T]:
        """Invoke an acquisition operation only after successful preflight."""

        approved = self.preflight(request, instruments=instruments)
        return approved, operation(request)

    def validate_instrument_scope(
        self,
        instruments: Iterable[str],
        *,
        request: OfficialRateRequest | None = None,
    ) -> tuple[str, ...]:
        scope = tuple(sorted(set(instruments)))
        prohibited = set(scope) & PROHIBITED_IDENTIFIERS
        unauthorized = set(scope) - AUTHORIZED_INSTRUMENTS
        if prohibited or unauthorized:
            if request is None:
                raise RateSourceError(
                    "NZDUSD_INSTRUMENT_PROHIBITED"
                    if prohibited
                    else "INSTRUMENT_SCOPE_NOT_AUTHORIZED"
                )
            self._reject(
                "NZDUSD_INSTRUMENT_PROHIBITED"
                if prohibited
                else "INSTRUMENT_SCOPE_NOT_AUTHORIZED",
                "REQUEST_PREFLIGHT",
                request,
            )
        return scope

    def validate_scope_label(
        self,
        approved: ApprovedHistoricalRequest,
        label: object,
    ) -> date:
        """Validate a non-numerical observation-date scope label."""

        request = self._verify_token(approved)
        return self._parse_and_validate_date(label, request)

    def validate_response(
        self,
        approved: ApprovedHistoricalRequest,
        document: object,
    ) -> CertifiedHistoricalResponse:
        """Certify a whole decoded response, exposing no rows on failure."""

        request = self._verify_token(approved)
        if not isinstance(document, Mapping) or set(document) != {"schema", "observations"}:
            self._reject("SOURCE_RESPONSE_SCHEMA_VIOLATION", "RESPONSE_FIREWALL", request)
        if document["schema"] != self.contract.schema_id:
            self._reject("SOURCE_RESPONSE_SCHEMA_VIOLATION", "RESPONSE_FIREWALL", request)
        observations = document["observations"]
        if not isinstance(observations, list):
            self._reject("SOURCE_RESPONSE_SCHEMA_VIOLATION", "RESPONSE_FIREWALL", request)

        accepted: list[Mapping[str, object]] = []
        seen: dict[tuple[str, str, date], str] = {}
        for raw_row in observations:
            if not isinstance(raw_row, Mapping):
                self._reject("SOURCE_RESPONSE_SCHEMA_VIOLATION", "RESPONSE_FIREWALL", request)
            row = cast(Mapping[str, object], raw_row)
            fields = frozenset(row)
            if fields != self.contract.required_row_fields or any(
                not isinstance(name, str) for name in fields
            ):
                self._reject(
                    "SOURCE_RESPONSE_SCHEMA_VIOLATION",
                    "RESPONSE_FIREWALL",
                    request,
                    field_names=tuple(sorted(str(name) for name in fields)),
                )
            series_id = row[self.contract.row_series_field]
            currency = row[self.contract.row_currency_field]
            if not isinstance(series_id, str) or series_id != request.series_id:
                self._reject("SOURCE_RESPONSE_SERIES_MISMATCH", "RESPONSE_FIREWALL", request)
            if not isinstance(currency, str) or currency != request.currency:
                self._reject("SOURCE_RESPONSE_CURRENCY_MISMATCH", "RESPONSE_FIREWALL", request)
            observation_date = self._parse_and_validate_date(
                row[self.contract.observation_date_field], request
            )
            try:
                signature = json.dumps(
                    dict(row), sort_keys=True, separators=(",", ":"), ensure_ascii=True
                )
            except (TypeError, ValueError):
                self._reject("SOURCE_RESPONSE_SCHEMA_VIOLATION", "RESPONSE_FIREWALL", request)
            identity = (currency, series_id, observation_date)
            previous = seen.get(identity)
            if previous is not None:
                if previous != signature:
                    self._reject(
                        "SOURCE_RESPONSE_DUPLICATE_CONFLICT",
                        "RESPONSE_FIREWALL",
                        request,
                        offending_date_label=observation_date.isoformat(),
                    )
                continue
            seen[identity] = signature
            accepted.append(dict(row))

        result = CertifiedHistoricalResponse(
            request_identity=request.request_identity,
            schema_id=self.contract.schema_id,
            rows=tuple(accepted),
        )
        self._certified_response_count += 1
        return result

    def _verify_token(self, approved: ApprovedHistoricalRequest) -> OfficialRateRequest:
        request = approved.request
        if approved.contract_fingerprint != self.contract.fingerprint:
            self._reject("REQUEST_PREFLIGHT_TOKEN_INVALID", "RESPONSE_FIREWALL", request)
        return request

    def _decode_snapshot(self, snapshot: SourceSnapshot) -> Mapping[str, object]:
        request = snapshot.request
        content_type = snapshot.content_type.partition(";")[0].strip().lower()
        response_format = self.contract.response_format.lower()
        if "json" in response_format:
            if content_type not in {"application/json", "text/json"}:
                self._reject(
                    "SOURCE_RESPONSE_FORMAT_VIOLATION", "RESPONSE_FIREWALL", request
                )
            try:
                decoded = json.loads(snapshot.payload)
            except (UnicodeDecodeError, json.JSONDecodeError):
                self._reject("SOURCE_RESPONSE_SCHEMA_VIOLATION", "RESPONSE_FIREWALL", request)
            if not isinstance(decoded, Mapping):
                self._reject("SOURCE_RESPONSE_SCHEMA_VIOLATION", "RESPONSE_FIREWALL", request)
            return cast(Mapping[str, object], decoded)
        if "csv" in response_format:
            if content_type not in {"text/csv", "application/csv"}:
                self._reject(
                    "SOURCE_RESPONSE_FORMAT_VIOLATION", "RESPONSE_FIREWALL", request
                )
            try:
                text = snapshot.payload.decode("utf-8-sig")
                reader = csv.DictReader(io.StringIO(text), strict=True)
                if frozenset(reader.fieldnames or ()) != self.contract.required_row_fields:
                    self._reject(
                        "SOURCE_RESPONSE_SCHEMA_VIOLATION", "RESPONSE_FIREWALL", request
                    )
                rows = list(reader)
            except (UnicodeDecodeError, csv.Error):
                self._reject("SOURCE_RESPONSE_SCHEMA_VIOLATION", "RESPONSE_FIREWALL", request)
            return {"schema": self.contract.schema_id, "observations": rows}
        self._reject("SOURCE_RESPONSE_FORMAT_VIOLATION", "RESPONSE_FIREWALL", request)

    def _parse_and_validate_date(self, value: object, request: OfficialRateRequest) -> date:
        label = value if isinstance(value, str) else None
        if label is None:
            self._reject("SOURCE_RESPONSE_DATE_MALFORMED", "RESPONSE_FIREWALL", request)
        try:
            parsed = date.fromisoformat(label)
        except ValueError:
            self._reject(
                "SOURCE_RESPONSE_DATE_MALFORMED",
                "RESPONSE_FIREWALL",
                request,
                offending_date_label=label,
            )
        if parsed.isoformat() != label:
            self._reject(
                "SOURCE_RESPONSE_DATE_MALFORMED",
                "RESPONSE_FIREWALL",
                request,
                offending_date_label=label,
            )
        if (
            parsed < self.contract.minimum_authorized_date
            or parsed > self.contract.maximum_authorized_date
            or parsed < request.start
            or parsed > request.end
        ):
            self._reject(
                SOURCE_RESPONSE_SCOPE_VIOLATION,
                "RESPONSE_FIREWALL",
                request,
                offending_date_label=label,
            )
        return parsed

    def _reject(
        self,
        code: str,
        stage: str,
        request: OfficialRateRequest,
        *,
        offending_date_label: str | None = None,
        field_names: tuple[str, ...] = (),
    ) -> NoReturn:
        violation = FirewallViolationRecord(
            code=code,
            stage=stage,
            request_identity=request.request_identity,
            allowlist_identity=self.contract.allowlist_identity,
            adapter_id=request.adapter_id,
            currency=request.currency,
            series_id=request.series_id,
            schema_id=self.contract.schema_id,
            request_start=request.start.isoformat(),
            request_end=request.end.isoformat(),
            offending_date_label=offending_date_label,
            field_names=field_names,
        )
        self._violations.append(violation)
        if stage == "RESPONSE_FIREWALL":
            self._quarantined_response_count += 1
        if self._audit_sink is not None:
            self._audit_sink.record(violation)
        raise HistoricalResponseFirewallError(violation)
