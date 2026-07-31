"""Authorized HTTP acquisition and immutable raw-snapshot persistence."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

import httpx

from fx_smc_bot.research.rate_sources.base import (
    OfficialRateRequest,
    RateAccessAuthorization,
    RateResponseFirewall,
    RateSourceError,
    SourceSnapshot,
)

CLIENT_VERSION = "F0RPE2ER_OFFICIAL_RATE_SNAPSHOT_CLIENT_V2"
PROVENANCE_HEADERS = frozenset(
    {"content-disposition", "content-length", "content-type", "date", "etag", "last-modified"}
)


class OfficialRateSnapshotClient:
    """Fetch only authorized GET requests and atomically retain their raw bytes."""

    def __init__(
        self,
        snapshot_root: Path,
        *,
        transport: httpx.BaseTransport | None = None,
        timeout_seconds: float = 30.0,
    ) -> None:
        if timeout_seconds <= 0 or timeout_seconds > 120:
            raise ValueError("timeout_seconds must be in (0, 120]")
        self.snapshot_root = Path(snapshot_root)
        self.timeout_seconds = timeout_seconds
        self.transport = transport

    def fetch(
        self,
        request: OfficialRateRequest,
        authorization: RateAccessAuthorization,
        *,
        response_firewall: RateResponseFirewall | None = None,
    ) -> SourceSnapshot:
        authorization.authorize(request)
        declaration = request.endpoint_declaration
        if declaration is not None:
            if response_firewall is None:
                raise RateSourceError("V2_RESPONSE_FIREWALL_REQUIRED_BEFORE_HTTP")
            if response_firewall.firewall_id != declaration.firewall_id:
                raise RateSourceError("V2_RESPONSE_FIREWALL_ID_MISMATCH")
            response_firewall.validate_request(request)
        retry_policy = declaration.retry_policy if declaration is not None else None
        maximum_attempts = retry_policy.maximum_attempts if retry_policy is not None else 1
        with httpx.Client(
            follow_redirects=False,
            timeout=self.timeout_seconds,
            transport=self.transport,
        ) as client:
            for attempt in range(1, maximum_attempts + 1):
                try:
                    response = client.request(
                        request.method,
                        request.url,
                        params=request.query_parameters,
                        headers=request.request_headers,
                    )
                except httpx.TransportError:
                    if retry_policy is None or attempt == maximum_attempts:
                        raise
                    time.sleep(retry_policy.backoff_seconds(attempt))
                    continue
                if (
                    retry_policy is None
                    or response.status_code not in retry_policy.retryable_status_codes
                    or attempt == maximum_attempts
                ):
                    break
                response.close()
                time.sleep(retry_policy.backoff_seconds(attempt))
        if response.is_redirect:
            raise RateSourceError("OFFICIAL_ENDPOINT_REDIRECT_REQUIRES_EXPLICIT_AUTHORIZATION")
        if response.status_code != 200:
            raise RateSourceError(f"OFFICIAL_ENDPOINT_HTTP_STATUS_{response.status_code}")
        final_host = (urlparse(str(response.url)).hostname or "").lower()
        if final_host not in authorization.official_hosts:
            raise RateSourceError("OFFICIAL_ENDPOINT_FINAL_HOST_NOT_AUTHORIZED")

        payload = bytes(response.content)
        digest = hashlib.sha256(payload).hexdigest()
        retrieved_at = datetime.now(UTC)
        headers = tuple(
            sorted(
                (name.lower(), value)
                for name, value in response.headers.multi_items()
                if name.lower() in PROVENANCE_HEADERS
            )
        )
        snapshot = SourceSnapshot(
            request=request,
            payload=payload,
            content_type=response.headers.get("content-type", ""),
            response_headers=headers,
            retrieved_at=retrieved_at,
            source_snapshot_sha256=digest,
        )
        if response_firewall is not None:
            response_firewall.validate_snapshot(snapshot)
        self._persist(snapshot)
        return snapshot

    def _persist(self, snapshot: SourceSnapshot) -> None:
        directory = (
            self.snapshot_root / snapshot.request.adapter_id / snapshot.request.request_identity
        )
        payload_path = directory / f"{snapshot.source_snapshot_sha256}.payload"
        metadata_path = directory / f"{snapshot.source_snapshot_sha256}.json"
        metadata = {
            "client_version": CLIENT_VERSION,
            "request_identity": snapshot.request.request_identity,
            "adapter_id": snapshot.request.adapter_id,
            "currency": snapshot.request.currency,
            "series_id": snapshot.request.series_id,
            "source_endpoint_role": snapshot.request.source_endpoint_role,
            "source_allowlist_identity": (
                snapshot.request.endpoint_declaration.allowlist_identity
                if snapshot.request.endpoint_declaration is not None
                else None
            ),
            "endpoint_declaration_sha256": (
                snapshot.request.endpoint_declaration.declaration_sha256
                if snapshot.request.endpoint_declaration is not None
                else None
            ),
            "schema_fingerprint": (
                snapshot.request.endpoint_declaration.schema_fingerprint
                if snapshot.request.endpoint_declaration is not None
                else None
            ),
            "retry_policy_id": (
                snapshot.request.endpoint_declaration.retry_policy.policy_id
                if snapshot.request.endpoint_declaration is not None
                else None
            ),
            "payload_sha256": snapshot.source_snapshot_sha256,
            "content_type": snapshot.content_type,
            "response_headers": list(snapshot.response_headers),
            "retrieved_at": snapshot.retrieved_at.isoformat(),
        }
        directory.mkdir(parents=True, exist_ok=True)
        self._create_once(payload_path, snapshot.payload)
        encoded = (json.dumps(metadata, allow_nan=False, indent=2, sort_keys=True) + "\n").encode(
            "utf-8"
        )
        self._create_metadata_once(metadata_path, encoded)

    @staticmethod
    def _create_metadata_once(path: Path, payload: bytes) -> None:
        if not path.exists():
            OfficialRateSnapshotClient._create_once(path, payload)
            return
        existing = json.loads(path.read_text(encoding="utf-8"))
        replay = json.loads(payload)
        existing.pop("retrieved_at", None)
        replay.pop("retrieved_at", None)
        if existing != replay:
            raise RateSourceError("IMMUTABLE_SOURCE_SNAPSHOT_METADATA_CONFLICT")

    @staticmethod
    def _create_once(path: Path, payload: bytes) -> None:
        if path.exists():
            if path.read_bytes() != payload:
                raise RateSourceError("IMMUTABLE_SOURCE_SNAPSHOT_CONFLICT")
            return
        fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        temporary = Path(temporary_name)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(temporary, path)
            except FileExistsError as exc:
                if path.read_bytes() != payload:
                    raise RateSourceError("IMMUTABLE_SOURCE_SNAPSHOT_CONFLICT") from exc
        finally:
            temporary.unlink(missing_ok=True)
