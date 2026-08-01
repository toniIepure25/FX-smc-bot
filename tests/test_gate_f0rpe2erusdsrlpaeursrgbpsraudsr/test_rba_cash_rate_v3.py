from __future__ import annotations

import hashlib
import math
import struct
import zipfile
from datetime import UTC, date, datetime, timedelta
from io import BytesIO
from pathlib import Path

import pytest

from fx_smc_bot.research.publication_censoring import (
    NEW_YORK_ZONE,
    PublicationEvidenceKind,
)
from fx_smc_bot.research.rate_sources.base import (
    OfficialRateRequest,
    RateAccessAuthorization,
    RateSourceError,
    SourceSnapshot,
)
from fx_smc_bot.research.rate_sources.rba import (
    RBA_F1_CURRENT_SCHEMA_FINGERPRINT,
    RBA_F1_HISTORICAL_SCHEMA_FINGERPRINT,
    RBA_F1_SHAPE_INSPECTOR_ID,
    RbaCashRateAdapterV3,
    rba_cash_rate_publication_evidence,
)
from fx_smc_bot.research.rate_vintage_store import (
    V4_SCHEMA_VERSION,
    AvailableRate,
    MissingRate,
    RateVintageStore,
)


def _authorization(start: date, end: date) -> RateAccessAuthorization:
    return RateAccessAuthorization(
        authorization_id=f"SYNTHETIC_RBA_V3_{start}_{end}",
        adapter_ids=frozenset({"RBA_CASH_RATE_V3"}),
        currencies=frozenset({"AUD"}),
        series_ids=frozenset({"RBA_CASH_RATE"}),
        start=start,
        end=end,
        official_hosts=frozenset({"www.rba.gov.au"}),
    )


def _request(start: date, end: date, *, current: bool) -> OfficialRateRequest:
    adapter = RbaCashRateAdapterV3()
    requests = adapter.build_requests(start, end, _authorization(start, end))
    return next(
        request
        for request in requests
        if (request.url.endswith(".xlsx") if current else request.url.endswith(".xls"))
    )


def _snapshot(request: OfficialRateRequest, payload: bytes, content_type: str) -> SourceSnapshot:
    return SourceSnapshot(
        request=request,
        payload=payload,
        content_type=content_type,
        response_headers=(("content-type", content_type),),
        retrieved_at=datetime(2026, 8, 1, tzinfo=UTC),
        source_snapshot_sha256=hashlib.sha256(payload).hexdigest(),
    )


def test_current_xlsx_selects_actual_cash_rate_and_quarantines_future_rows(
    tmp_path: Path,
) -> None:
    adapter = RbaCashRateAdapterV3()
    request = _request(date(2016, 1, 4), date(2016, 1, 4), current=True)
    snapshot = _snapshot(request, _current_xlsx(), "application/octet-stream")

    shape = adapter.certify_snapshot_shape(snapshot)
    versions = adapter.parse_snapshot(snapshot)
    version = versions[0]

    assert shape.inspector_id == RBA_F1_SHAPE_INSPECTOR_ID
    assert shape.schema_fingerprint == RBA_F1_CURRENT_SCHEMA_FINGERPRINT
    assert shape.row_count == 1
    assert version.observation_date == date(2016, 1, 4)
    assert version.value == pytest.approx(0.02)
    assert version.publication_timestamp is None
    assert version.publication_evidence_kind == (
        PublicationEvidenceKind.PUBLICATION_DAY_ENVELOPE.value
    )
    assert ("cash_rate_column", "D") in version.source_metadata
    assert ("post_2022_dates_structurally_encountered", "True") in version.source_metadata
    assert adapter.certify_version(version).status == "PASS"

    with RateVintageStore(tmp_path / "aud-v4.sqlite3", schema_version=V4_SCHEMA_VERSION) as store:
        store.append_source_snapshot(snapshot, firewall_certification=shape)
        version_id = store.append_rate_version(version)
        store.append_certification(
            version_id,
            status="PASS",
            certified_at=datetime(2026, 8, 1, 12, tzinfo=UTC),
        )
        freeze = store.create_dataset_freeze(
            "SYNTHETIC_RBA_V3_FREEZE",
            [version_id],
            created_at=datetime(2026, 8, 1, 13, tzinfo=UTC),
        )
        before = store.get_rate_as_of(
            "AUD",
            version.strategy_availability_timestamp - timedelta(seconds=1),
            freeze.dataset_freeze_id,
        )
        at = store.get_rate_as_of(
            "AUD",
            version.strategy_availability_timestamp,
            freeze.dataset_freeze_id,
        )

    assert isinstance(before, MissingRate)
    assert isinstance(at, AvailableRate)
    assert at.schema_fingerprint == RBA_F1_CURRENT_SCHEMA_FINGERPRINT


def test_historical_xls_parses_2010_boundary_without_target_substitution() -> None:
    adapter = RbaCashRateAdapterV3()
    request = _request(date(2010, 12, 20), date(2010, 12, 20), current=False)
    snapshot = _snapshot(request, _historical_xls(), "application/octet-stream")

    shape = adapter.certify_snapshot_shape(snapshot)
    version = adapter.parse_snapshot(snapshot)[0]

    assert shape.schema_fingerprint == RBA_F1_HISTORICAL_SCHEMA_FINGERPRINT
    assert version.observation_date == date(2010, 12, 20)
    assert version.value == pytest.approx(0.0475)
    assert ("cash_rate_column", "D") in version.source_metadata
    assert ("series_code", "FIRMMCRID") in version.source_metadata
    assert adapter.certify_version(version).passed is True


def test_publication_day_envelope_is_conservative_and_dst_aware() -> None:
    ordinary = rba_cash_rate_publication_evidence(date(2016, 1, 4))
    year_end = rba_cash_rate_publication_evidence(date(2022, 12, 30))

    assert ordinary.publication_date == date(2016, 1, 5)
    assert ordinary.publication_lower_bound == datetime(
        2016, 1, 5, 0, 0, tzinfo=ordinary.publication_lower_bound.tzinfo
    )
    assert ordinary.publication_upper_bound_exclusive is True
    assert ordinary.strategy_availability_timestamp == datetime(
        2016, 1, 5, 17, 5, tzinfo=NEW_YORK_ZONE
    )
    assert year_end.publication_date == date(2023, 1, 3)
    assert year_end.strategy_availability_timestamp == datetime(
        2023, 1, 3, 17, 5, tzinfo=NEW_YORK_ZONE
    )


def test_target_column_unknown_schema_and_quarantined_request_fail_closed() -> None:
    adapter = RbaCashRateAdapterV3()
    request = _request(date(2016, 1, 4), date(2016, 1, 4), current=True)

    with pytest.raises(RateSourceError, match="SCHEMA_CHANGED"):
        adapter.parse_snapshot(
            _snapshot(
                request,
                _current_xlsx(cash_rate_series_code="FIRMMCRTD"),
                "application/octet-stream",
            )
        )
    with pytest.raises(RateSourceError, match="QUARANTINED"):
        adapter.build_requests(
            date(2023, 1, 3),
            date(2023, 1, 3),
            _authorization(date(2023, 1, 3), date(2023, 1, 3)),
        )


def _current_xlsx(*, cash_rate_series_code: str = "FIRMMCRID") -> bytes:
    rows = [
        _row(1, {"A": _inline("F1 INTEREST RATES AND YIELDS - MONEY MARKET")}),
        _row(
            2,
            {
                "B": _inline("Cash Rate Target"),
                "D": _inline("Interbank Overnight Cash Rate"),
                "I": _inline("Total Return Index"),
            },
        ),
        _row(3, {"D": _inline("Interbank Overnight Cash Rate on date")}),
        _row(6, {"D": _inline("Per cent")}),
        _row(9, {"D": _inline("RBA")}),
        _row(11, {"B": _inline("FIRMMCRTD"), "D": _inline(cash_rate_series_code)}),
        _row(12, {"A": _number(_excel_serial(date(2016, 1, 4))), "D": _number(2.0)}),
        _row(13, {"A": _number(_excel_serial(date(2023, 1, 3))), "D": _number(999.0)}),
    ]
    sheet = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        "<sheetData>" + "".join(rows) + "</sheetData></worksheet>"
    )
    workbook = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        "<sheets>"
        '<sheet name="Data" sheetId="1" r:id="rId1"/>'
        '<sheet name="Notes" sheetId="2" r:id="rId2"/>'
        '<sheet name="Use of Expert Judgement" sheetId="3" r:id="rId3"/>'
        "</sheets></workbook>"
    )
    rels = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="worksheet" Target="worksheets/sheet1.xml"/>'
        '<Relationship Id="rId2" Type="worksheet" Target="worksheets/sheet2.xml"/>'
        '<Relationship Id="rId3" Type="worksheet" Target="worksheets/sheet3.xml"/>'
        "</Relationships>"
    )
    out = BytesIO()
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("xl/workbook.xml", workbook)
        archive.writestr("xl/_rels/workbook.xml.rels", rels)
        archive.writestr("xl/worksheets/sheet1.xml", sheet)
        archive.writestr("xl/worksheets/sheet2.xml", "<worksheet/>")
        archive.writestr("xl/worksheets/sheet3.xml", "<worksheet/>")
    return out.getvalue()


def _historical_xls() -> bytes:
    strings = [
        "F1 INTEREST RATES AND YIELDS - MONEY MARKET",
        "Title",
        "Cash Rate Target",
        "Change in the Cash Rate Target ",
        "Interbank Overnight Cash Rate",
        "Description",
        "Cash Rate Target on date",
        "Change in the Cash Rate Target (in percentage points)",
        "Interbank Overnight Cash Rate on date",
        "Units",
        "Per cent",
        "Source",
        "RBA",
        "Series ID",
        "FIRMMCRTD",
        "FIRMMCCRT",
        "FIRMMCRID",
    ]
    labels = [
        (0, 0, 0),
        (1, 0, 1),
        (1, 1, 2),
        (1, 2, 3),
        (1, 3, 4),
        (2, 0, 5),
        (2, 1, 6),
        (2, 2, 7),
        (2, 3, 8),
        (5, 0, 9),
        (5, 1, 10),
        (5, 2, 10),
        (5, 3, 10),
        (8, 0, 11),
        (8, 1, 12),
        (8, 2, 12),
        (8, 3, 12),
        (10, 0, 13),
        (10, 1, 14),
        (10, 2, 15),
        (10, 3, 16),
    ]
    data_sheet = (
        _rec(0x0809, struct.pack("<HHHHHH", 0x0600, 0x0010, 0, 0, 0, 0))
        + b"".join(_rec(0x00FD, struct.pack("<HHHI", row, col, 0, idx)) for row, col, idx in labels)
        + _rec(0x0203, struct.pack("<HHHd", 11, 0, 0, _excel_serial(date(2010, 12, 20))))
        + _rec(0x0203, struct.pack("<HHHd", 11, 3, 0, 4.75))
        + _rec(0x000A, b"")
    )
    notes_sheet = _rec(0x0809, struct.pack("<HHHHHH", 0x0600, 0x0010, 0, 0, 0, 0)) + _rec(
        0x000A, b""
    )
    globals_without_bounds = _rec(0x0809, struct.pack("<HHHHHH", 0x0600, 0x0005, 0, 0, 0, 0))
    sst = _sst(strings)
    bounds_len = len(_boundsheet(0, "Data") + _boundsheet(0, "Notes"))
    data_offset = len(globals_without_bounds) + bounds_len + len(sst) + len(_rec(0x000A, b""))
    notes_offset = data_offset + len(data_sheet)
    workbook = (
        globals_without_bounds
        + _boundsheet(data_offset, "Data")
        + _boundsheet(notes_offset, "Notes")
        + sst
        + _rec(0x000A, b"")
        + data_sheet
        + notes_sheet
    )
    return _ole_with_workbook(workbook)


def _row(index: int, cells: dict[str, str]) -> str:
    body = "".join(f'<c r="{col}{index}"{xml}>{value}</c>' for col, (xml, value) in cells.items())
    return f'<row r="{index}">{body}</row>'


def _inline(text: str) -> tuple[str, str]:
    return ' t="inlineStr"', f"<is><t>{text}</t></is>"


def _number(value: float) -> tuple[str, str]:
    return "", f"<v>{value}</v>"


def _excel_serial(day: date) -> float:
    return float((day - date(1899, 12, 30)).days)


def _rec(record_id: int, payload: bytes) -> bytes:
    return struct.pack("<HH", record_id, len(payload)) + payload


def _sst(strings: list[str]) -> bytes:
    payload = struct.pack("<II", len(strings), len(strings))
    for text in strings:
        raw = text.encode("latin1")
        payload += struct.pack("<HB", len(raw), 0) + raw
    return _rec(0x00FC, payload)


def _boundsheet(offset: int, name: str) -> bytes:
    raw = name.encode("latin1")
    return _rec(0x0085, struct.pack("<IBBB", offset, 0, 0, len(raw)) + b"\x00" + raw)


def _ole_with_workbook(workbook: bytes) -> bytes:
    sector_size = 512
    workbook_sectors = math.ceil(len(workbook) / sector_size)
    fat_entries = [0xFFFFFFFD, 0xFFFFFFFE]
    for index in range(workbook_sectors):
        fat_entries.append(0xFFFFFFFE if index == workbook_sectors - 1 else 3 + index)
    fat_entries.extend([0xFFFFFFFF] * (128 - len(fat_entries)))
    fat_sector = b"".join(struct.pack("<I", item) for item in fat_entries)
    directory = _dir_entry("Root Entry", 5, 0xFFFFFFFE, 0) + _dir_entry(
        "Workbook", 2, 2, len(workbook)
    )
    directory = directory.ljust(sector_size, b"\x00")
    workbook_payload = workbook.ljust(workbook_sectors * sector_size, b"\x00")
    header = bytearray(512)
    header[:8] = bytes.fromhex("d0cf11e0a1b11ae1")
    struct.pack_into("<HHHHH", header, 24, 0x003E, 0x0003, 0xFFFE, 9, 6)
    struct.pack_into("<I", header, 44, 1)
    struct.pack_into("<I", header, 48, 1)
    struct.pack_into("<I", header, 56, 4096)
    struct.pack_into("<I", header, 60, 0xFFFFFFFE)
    struct.pack_into("<I", header, 68, 0xFFFFFFFE)
    struct.pack_into("<I", header, 76, 0)
    for index in range(1, 109):
        struct.pack_into("<I", header, 76 + index * 4, 0xFFFFFFFF)
    return bytes(header) + fat_sector + directory + workbook_payload


def _dir_entry(name: str, stream_type: int, start: int, size: int) -> bytes:
    entry = bytearray(128)
    raw_name = name.encode("utf-16le") + b"\x00\x00"
    entry[: len(raw_name)] = raw_name
    struct.pack_into("<H", entry, 64, len(raw_name))
    entry[66] = stream_type
    struct.pack_into("<III", entry, 68, 0xFFFFFFFF, 0xFFFFFFFF, 0xFFFFFFFF)
    struct.pack_into("<I", entry, 116, start)
    struct.pack_into("<Q", entry, 120, size)
    return bytes(entry)
