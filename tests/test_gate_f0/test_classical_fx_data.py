from __future__ import annotations

import ast
import json
import subprocess
from concurrent.futures import Future
from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from fx_smc_bot.research import classical_fx_data as data
from fx_smc_bot.research.classical_factor_safe_io import (
    DataProvider,
    IOAuthorization,
    MarketPartition,
    OperationType,
    ProviderRequest,
)


def _partition(side: str = "bid") -> MarketPartition:
    return MarketPartition("EURUSD", side, date(2010, 1, 1), date(2010, 1, 31))


def _payload(side_offset: float = 0.0) -> bytes:
    base = int(datetime(2010, 1, 4, tzinfo=UTC).timestamp() * 1000)
    rows = []
    for minute in range(10):
        price = 1.10 + side_offset + minute / 10_000
        rows.append(
            {
                "timestamp": base + minute * 60_000,
                "open": price,
                "high": price + 0.0002,
                "low": price - 0.0002,
                "close": price + 0.0001,
            }
        )
    return json.dumps(rows).encode()


def _authorization(operation: OperationType, tmp_path: Path) -> IOAuthorization:
    return IOAuthorization(
        clean_room_root=tmp_path,
        authorized_instruments=frozenset({"EURUSD"}),
        authorized_currencies=frozenset({"EUR", "USD"}),
        authorized_start=date(2010, 1, 1),
        authorized_end=date(2010, 1, 31),
        authorized_partition_set=frozenset({_partition()}),
        authorized_provider=DataProvider.DUKASCOPY_BI5_BID_ASK,
        authorized_operation=operation,
        repository_root=tmp_path / "repository",
        forbidden_roots=(),
    )


def _m5_row(timestamp: datetime, price: float) -> dict[str, int | float]:
    row: dict[str, int | float] = {"timestamp": int(timestamp.timestamp() * 1000)}
    for side, offset in (("bid", 0.0), ("ask", 0.001)):
        row[f"{side}_open"] = price + offset
        row[f"{side}_high"] = price + offset + 0.0002
        row[f"{side}_low"] = price + offset - 0.0002
        row[f"{side}_close"] = price + offset + 0.0001
    return row


def test_development_plan_has_exactly_1680_unique_monthly_tasks() -> None:
    plan = data.development_plan()
    assert plan["partition_tasks"] == 1_680
    assert plan["pair_months"] == 840
    assert len(plan["tasks"]) == 1_680
    assert len({task["partition_id"] for task in plan["tasks"]}) == 1_680
    assert plan["tasks"][0]["start"] == "2010-01-01"
    assert plan["tasks"][-1]["end"] == "2016-12-31"
    assert plan["provider"]["pause_between_batches_ms"] == 200
    assert plan["provider"]["cache"] is False
    assert (
        plan["canonicalization"]["aggregation_chain"] == "M1_TO_CERTIFIED_M5_TO_CROSS_MONTH_DAILY"
    )
    assert plan["storage"]["minimum_free_reserve_bytes"] == 10 * 1024**3
    data.verify_development_plan(plan)


def test_plan_hash_is_deterministic_and_covers_tasks() -> None:
    first = data.development_plan()
    second = data.development_plan()
    assert first == second
    tampered = dict(first)
    tampered["partition_tasks"] = 1_679
    with pytest.raises(ValueError, match="hash mismatch"):
        data.verify_development_plan(tampered)


@pytest.mark.parametrize(
    ("start", "end"),
    [
        (date(2009, 12, 31), date(2016, 12, 31)),
        (date(2010, 1, 1), date(2017, 1, 1)),
        (date(2011, 1, 1), date(2016, 12, 31)),
        (date(2010, 1, 1), date(2015, 12, 31)),
    ],
)
def test_development_command_rejects_every_nonfrozen_date_range(start: date, end: date) -> None:
    with pytest.raises(ValueError, match="exactly"):
        data.development_plan(start=start, end=end)


@pytest.mark.parametrize("workers", [0, 9, -1])
def test_worker_count_is_bounded(workers: int, tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="between 1 and 8"):
        data.acquire_development_market(tmp_path, tmp_path / "repo", workers=workers)


def test_acquisition_default_dry_run_calls_no_guard_callback_or_subprocess(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("dry-run crossed an execution boundary")

    monkeypatch.setattr(data, "safe_provider_request", forbidden)
    monkeypatch.setattr(data.subprocess, "run", forbidden)
    monkeypatch.setattr(data, "development_authorizations", forbidden)
    result = data.acquire_development_market(tmp_path, tmp_path / "repo")
    assert result["status"] == "DRY_RUN_NO_PROVIDER_ACCESS"
    assert result["provider_requests_sent"] == 0
    assert result["planned_partitions"] == 1_680


def test_certification_default_dry_run_performs_no_local_io(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        data,
        "development_authorizations",
        lambda *_args, **_kwargs: pytest.fail("dry-run touched local I/O"),
    )
    result = data.certify_development_market(tmp_path, tmp_path / "repo")
    assert result["status"] == "DRY_RUN_NO_LOCAL_IO"
    assert result["planned_pair_months"] == 840


def test_subprocess_occurs_only_inside_safe_provider_callback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    bundle = data.AuthorizationBundle(
        provider=_authorization(OperationType.PROVIDER_REQUEST, tmp_path),
        read=_authorization(OperationType.READ, tmp_path),
        write=_authorization(OperationType.WRITE, tmp_path),
        stat=_authorization(OperationType.STAT, tmp_path),
        delete=_authorization(OperationType.DELETE, tmp_path),
    )

    monkeypatch.setattr(data, "_raw_manifest_is_current", lambda *_args: False)
    monkeypatch.setattr(data, "safe_prepare_partition_directory", lambda *_args: tmp_path)
    monkeypatch.setattr(data, "_node_command", lambda *_args: ["node", "f0-wrapper"])
    monkeypatch.setattr(data, "safe_read_bytes", lambda *_args: _payload())
    monkeypatch.setattr(data, "safe_atomic_write", lambda *_args: "a" * 64)
    monkeypatch.setattr(data, "safe_unlink", lambda *_args: None)

    def guarded(
        _authorization: IOAuthorization,
        request: ProviderRequest,
        callback: Any,
    ) -> subprocess.CompletedProcess[str]:
        events.append("safe_provider_request")
        assert request.start == date(2010, 1, 1)
        events.append("callback")
        return callback(request)

    def runner(*_args: Any, **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        events.append("subprocess")
        return subprocess.CompletedProcess(["node"], 0, "", "")

    def storage(root: Path) -> SimpleNamespace:
        assert root == tmp_path
        events.append("storage")
        return SimpleNamespace(free=data.MINIMUM_FREE_SPACE_RESERVE_BYTES)

    monkeypatch.setattr(data, "safe_provider_request", guarded)
    result = data._acquire_partition(tmp_path / "repo", bundle, _partition(), runner, storage)
    assert result["status"] == "F0_RAW_COMPLETE"
    assert events == ["safe_provider_request", "callback", "storage", "subprocess"]


def test_storage_guard_blocks_before_provider_runner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = data.AuthorizationBundle(
        provider=_authorization(OperationType.PROVIDER_REQUEST, tmp_path),
        read=_authorization(OperationType.READ, tmp_path),
        write=_authorization(OperationType.WRITE, tmp_path),
        stat=_authorization(OperationType.STAT, tmp_path),
        delete=_authorization(OperationType.DELETE, tmp_path),
    )
    monkeypatch.setattr(data, "_raw_manifest_is_current", lambda *_args: False)
    monkeypatch.setattr(
        data,
        "safe_provider_request",
        lambda _authorization, request, callback: callback(request),
    )
    runner_called = False

    def runner(*_args: Any, **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        nonlocal runner_called
        runner_called = True
        return subprocess.CompletedProcess(["node"], 0, "", "")

    checked_roots: list[Path] = []

    def insufficient(root: Path) -> SimpleNamespace:
        checked_roots.append(root)
        return SimpleNamespace(free=data.MINIMUM_FREE_SPACE_RESERVE_BYTES - 1)

    with pytest.raises(RuntimeError, match="10 GiB"):
        data._acquire_partition(tmp_path / "repo", bundle, _partition(), runner, insufficient)
    assert checked_roots == [tmp_path]
    assert not runner_called


def test_first_future_failure_cancels_pending_work() -> None:
    failed: Future[dict[str, Any]] = Future()
    pending: Future[dict[str, Any]] = Future()
    failed.set_exception(RuntimeError("first failure"))
    with pytest.raises(RuntimeError, match="first failure"):
        data._collect_futures_fail_fast({failed: "failed", pending: "pending"})
    assert pending.cancelled()


def test_guard_rejection_prevents_subprocess(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = data.AuthorizationBundle(
        provider=_authorization(OperationType.PROVIDER_REQUEST, tmp_path),
        read=_authorization(OperationType.READ, tmp_path),
        write=_authorization(OperationType.WRITE, tmp_path),
        stat=_authorization(OperationType.STAT, tmp_path),
        delete=_authorization(OperationType.DELETE, tmp_path),
    )
    called = False
    monkeypatch.setattr(data, "_raw_manifest_is_current", lambda *_args: False)

    def reject(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("guard rejected")

    def runner(*_args: Any, **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        nonlocal called
        called = True
        return subprocess.CompletedProcess(["node"], 0, "", "")

    monkeypatch.setattr(data, "safe_provider_request", reject)
    with pytest.raises(RuntimeError, match="guard rejected"):
        data._acquire_partition(tmp_path / "repo", bundle, _partition(), runner)
    assert not called


def test_m1_to_m5_and_daily_aggregation_is_deterministic() -> None:
    bid = _payload()
    ask = _payload(0.001)
    first = data.canonicalize_pair_month(bid, ask, _partition("bid"), _partition("ask"))
    second = data.canonicalize_pair_month(bid, ask, _partition("bid"), _partition("ask"))
    assert data.canonical_json_bytes(first) == data.canonical_json_bytes(second)
    assert len(first["m1"]) == 10
    assert len(first["m5"]) == 2
    assert first["m5"][0]["bid_open"] == pytest.approx(1.10)
    assert first["m5"][0]["bid_close"] == pytest.approx(1.1005)
    assert first["m5"][0]["bid_high"] == pytest.approx(1.1006)
    assert first["m5"][0]["bid_low"] == pytest.approx(1.0998)
    assert first["m5_certification"]["incomplete_buckets"] == []
    assert len(first["daily_fragments"]) == 1
    assert first["daily_fragments"][0]["fx_close_date"] == "2010-01-04"
    assert "daily" not in first


def test_incomplete_m5_bucket_is_reported_and_never_filled() -> None:
    bid_rows = json.loads(_payload())
    ask_rows = json.loads(_payload(0.001))
    bid_rows.pop(3)
    ask_rows.pop(3)
    bid = data.parse_m1_payload(json.dumps(bid_rows).encode(), _partition("bid"))
    ask = data.parse_m1_payload(json.dumps(ask_rows).encode(), _partition("ask"))
    combined = data._combine_sides(bid, ask)
    result = data.aggregate_m5(combined)
    assert len(result["certified_bars"]) == 1
    assert len(result["incomplete_buckets"]) == 1
    assert result["incomplete_buckets"][0]["reason"].endswith("NO_FILL")
    assert len(result["incomplete_buckets"][0]["missing_timestamps"]) == 1


def test_cross_month_daily_assembly_uses_certified_m5_and_strict_deduplication() -> None:
    january = _m5_row(datetime(2010, 1, 31, 22, 0, tzinfo=UTC), 1.10)
    february_close = _m5_row(datetime(2010, 2, 1, 21, 55, tzinfo=UTC), 1.20)
    fragments = [
        *data.daily_fragments_from_certified_m5([january]),
        *data.daily_fragments_from_certified_m5([february_close]),
    ]
    result = data.assemble_daily_from_m5_fragments(fragments)
    assert result["incomplete_days"] == []
    assert len(result["certified_daily_bars"]) == 1
    daily = result["certified_daily_bars"][0]
    assert daily["fx_close_date"] == "2010-02-01"
    assert daily["bid_open"] == pytest.approx(january["bid_open"])
    assert daily["bid_close"] == pytest.approx(february_close["bid_close"])

    with pytest.raises(ValueError, match="strictly unique"):
        data.assemble_daily_from_m5_fragments([fragments[0], fragments[0]])


def test_daily_requires_exact_final_m5_before_new_york_close() -> None:
    penultimate = _m5_row(datetime(2010, 7, 1, 20, 50, tzinfo=UTC), 1.10)
    exact_final = _m5_row(datetime(2010, 7, 1, 20, 55, tzinfo=UTC), 1.20)

    incomplete = data.aggregate_daily([penultimate])
    assert incomplete["certified_daily_bars"] == []
    assert incomplete["incomplete_days"][0]["reason"].endswith("NO_FILL")

    complete = data.aggregate_daily([penultimate, exact_final])
    assert len(complete["certified_daily_bars"]) == 1
    assert complete["certified_daily_bars"][0]["fx_close_date"] == "2010-07-01"


def test_new_york_close_label_handles_dst_with_iana_timezone() -> None:
    before_close = int(datetime(2010, 7, 1, 20, 59, tzinfo=UTC).timestamp() * 1000)
    at_close = int(datetime(2010, 7, 1, 21, 0, tzinfo=UTC).timestamp() * 1000)
    assert data.fx_close_date(before_close) == "2010-07-01"
    assert data.fx_close_date(at_close) == "2010-07-02"
    assert data._final_m5_before_ny_close("2010-07-01") == int(
        datetime(2010, 7, 1, 20, 55, tzinfo=UTC).timestamp() * 1000
    )
    assert data._final_m5_before_ny_close("2010-01-04") == int(
        datetime(2010, 1, 4, 21, 55, tzinfo=UTC).timestamp() * 1000
    )


def test_node_request_uses_frozen_pause_and_disabled_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(data, "_verify_pinned_node_wrapper", lambda _root: tmp_path / "x.mjs")
    command = data._node_command(tmp_path, _partition(), tmp_path / "out")
    pause_index = command.index("--pauseBetweenBatchesMs")
    cache_index = command.index("--cache")
    assert command[pause_index + 1] == "200"
    assert command[cache_index + 1] == "false"


def test_parser_rejects_nonmatching_sides_and_payload_escape() -> None:
    with pytest.raises(ValueError, match="match exactly"):
        rows = json.loads(_payload(0.001))
        rows.pop()
        data.canonicalize_pair_month(
            _payload(), json.dumps(rows).encode(), _partition("bid"), _partition("ask")
        )
    escaped = json.loads(_payload())
    escaped[0]["timestamp"] = int(datetime(2017, 1, 1, tzinfo=UTC).timestamp() * 1000)
    with pytest.raises(ValueError, match="increasing|escapes"):
        data.parse_m1_payload(json.dumps(escaped).encode(), _partition())


def test_static_status_is_nonempirical_and_noninspecting() -> None:
    status = data.static_status()
    assert status["provider_requests_sent"] == 0
    assert status["filesystem_inspected"] is False
    assert status["default_mode"] == "DRY_RUN"


def test_f0_module_and_runner_use_no_broad_discovery_or_shell_api() -> None:
    repository = Path(data.__file__).resolve().parents[3]
    files = (Path(data.__file__), repository / "scripts" / "run_gate_f0.py")
    forbidden_attributes = {"glob", "rglob", "walk", "scandir", "Popen", "call", "check_call"}
    for path in files:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        used = {
            node.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Attribute) and node.attr in forbidden_attributes
        }
        assert used == set()
        source = path.read_text(encoding="utf-8")
        assert "shell=True" not in source
        assert "provider-payload.json" in source or path.name == "run_gate_f0.py"
        assert "f0-checkpoint.json" in source or path.name == "run_gate_f0.py"


def test_all_operational_resources_are_f0_namespaced() -> None:
    resources = (
        data.F0_PROVIDER_PAYLOAD,
        data.F0_RAW_M1,
        data.F0_RAW_MANIFEST,
        data.F0_CHECKPOINT,
        data.F0_CANONICAL_M1,
        data.F0_CANONICAL_M5,
        data.F0_DAILY_FRAGMENTS,
        data.F0_CANONICAL_DAILY,
        data.F0_CERTIFICATION,
        data.F0_DAILY_ASSEMBLY_CERTIFICATION,
    )
    assert all(name.startswith("f0-") and name.endswith(".json") for name in resources)
