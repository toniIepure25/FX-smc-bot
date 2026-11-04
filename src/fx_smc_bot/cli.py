"""Command-line entry point for the FX-SMC research framework.

The CLI is deliberately small and explicit. Research-gate runners remain frozen
scripts; this command covers the repeatable developer workflow: inspect the
project, validate a checkout, run a smoke backtest and launch the local cockpit.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import platform
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from fx_smc_bot import __version__
from fx_smc_bot.config import AppConfig, TradingPair
from fx_smc_bot.data.models import BarSeries
from fx_smc_bot.research.experiments import load_config

STATUS = "CURRENT_DATA_ALPHA_SEARCH_EXHAUSTED"
HOLDOUT = "sealed and unread (2018+)"
DEFAULT_CONFIG = Path("configs/base.yaml")
DEFAULT_DASHBOARD = Path("dashboard/app.py")


@dataclass(frozen=True)
class Check:
    """One environment or repository check."""

    name: str
    status: str
    detail: str

    def as_dict(self) -> dict[str, str]:
        return asdict(self)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _resolve_config(path: str | None) -> AppConfig:
    if path:
        config_path = Path(path)
    elif DEFAULT_CONFIG.exists():
        config_path = DEFAULT_CONFIG
    else:
        return AppConfig()
    return load_config(config_path)


def _find_dashboard(app: str | None) -> Path | None:
    candidates = [Path(app)] if app else [
        DEFAULT_DASHBOARD,
        _repo_root() / DEFAULT_DASHBOARD,
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    return None


def _cmd_info(args: argparse.Namespace) -> int:
    payload: dict[str, Any] = {
        "name": "fx-smc-bot",
        "version": __version__,
        "python": platform.python_version(),
        "status": STATUS,
        "holdout": HOLDOUT,
        "commands": ["info", "doctor", "data", "backtest", "dashboard"],
    }
    if args.json:
        print(json.dumps(payload, indent=2))
        return 0

    print("FX-SMC research framework")
    print(f"  version : {payload['version']}")
    print(f"  python  : {payload['python']}")
    print(f"  status  : {STATUS}")
    print(f"  holdout : {HOLDOUT}")
    print()
    print("This is a research artifact, not a trading signal service.")
    print("Use 'fx-smc doctor' to validate the checkout and")
    print("'fx-smc backtest --synthetic' for a self-contained smoke run.")
    return 0


def _cmd_doctor(args: argparse.Namespace) -> int:
    checks: list[Check] = []

    py_ok = sys.version_info >= (3, 10)
    checks.append(
        Check(
            "python",
            "ok" if py_ok else "fail",
            f"{platform.python_version()} (requires >= 3.10)",
        )
    )

    root = Path.cwd()
    repo_ok = (root / "pyproject.toml").is_file() and (root / "src" / "fx_smc_bot").is_dir()
    checks.append(
        Check(
            "repository",
            "ok" if repo_ok else "warn",
            str(root) if repo_ok else f"{root} does not look like the repository root",
        )
    )

    config_path = Path(args.config or DEFAULT_CONFIG)
    try:
        config = _resolve_config(args.config)
        checks.append(
            Check(
                "config",
                "ok",
                f"{config_path} | {len(config.data.primary_pairs)} pairs | "
                f"{len(config.data.execution_timeframes)} execution timeframes",
            )
        )
    except Exception as exc:
        checks.append(Check("config", "fail", f"{config_path}: {exc}"))
        config = None

    if args.data_dir:
        if config is None:
            checks.append(
                Check("data", "fail", "cannot audit data without a valid config")
            )
        else:
            from fx_smc_bot.data.audit import audit_market_data

            audit = audit_market_data(config, args.data_dir)
            if audit.error:
                detail = f"{audit.data_dir} | {audit.error}"
            else:
                total_bars = sum(pair.bars for pair in audit.pairs)
                min_quality = min((pair.quality_score for pair in audit.pairs), default=0.0)
                detail = (
                    f"{audit.data_dir} | {len(audit.loaded_pairs)}/"
                    f"{len(audit.configured_pairs)} pairs | {total_bars:,} bars | "
                    f"quality {min_quality:.2f}"
                )
                if audit.missing_pairs:
                    detail += f" | missing {', '.join(audit.missing_pairs)}"
                fallbacks = [pair.pair for pair in audit.pairs if not pair.timeframe_ok]
                if fallbacks:
                    detail += f" | fallback {', '.join(fallbacks)}"
            checks.append(Check("data", audit.status, detail))
    else:
        checks.append(Check("data", "skip", "no --data-dir supplied; synthetic path is available"))

    for module in ("streamlit", "plotly"):
        found = importlib.util.find_spec(module) is not None
        checks.append(
            Check(
                "dashboard-extra",
                "ok" if found else "warn",
                f"{module}: {'installed' if found else 'missing (pip install -e .[dashboard])'}",
            )
        )

    failures = [check for check in checks if check.status == "fail"]
    warnings = [check for check in checks if check.status == "warn"]
    exit_code = 1 if failures or (args.strict and warnings) else 0

    if args.json:
        print(
            json.dumps(
                {
                    "status": "fail" if exit_code else "ok",
                    "strict": args.strict,
                    "checks": [check.as_dict() for check in checks],
                },
                indent=2,
            )
        )
        return exit_code

    for check in checks:
        print(f"[{check.status:4}] {check.name:16} {check.detail}")
    print()
    if exit_code:
        message = (
            "Doctor found blocking issues."
            if failures
            else "Doctor found warnings (strict mode)."
        )
        print(message)
    else:
        print("Doctor: checkout is usable.")
    return exit_code


def _sha256_json(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _data_fingerprint(data: dict[TradingPair, BarSeries]) -> str:
    """Hash the exact timestamps and OHLCV arrays used by a run."""
    digest = hashlib.sha256()
    for pair in sorted(data):
        series = data[pair]
        digest.update(f"pair={pair.value};tf={series.timeframe.value};bars={len(series)}>".encode())
        for name in ("timestamps", "open", "high", "low", "close", "volume", "spread"):
            array = getattr(series, name)
            if array is None:
                digest.update(f"|{name}:none".encode())
                continue
            contiguous = np.ascontiguousarray(array)
            digest.update(f"|{name}:{contiguous.dtype}>".encode())
            digest.update(contiguous.tobytes())
    return digest.hexdigest()


def _cmd_data(args: argparse.Namespace) -> int:
    from fx_smc_bot.data.audit import audit_market_data, format_data_audit

    config = _resolve_config(args.config)
    audit = audit_market_data(config, args.data_dir)
    payload = audit.as_dict()

    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(format_data_audit(audit))

    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    if audit.status == "fail":
        return 1
    if args.strict and audit.status == "warn":
        return 1
    return 0


def _cmd_backtest(args: argparse.Namespace) -> int:
    from fx_smc_bot.backtesting.runner import load_market_data, run_backtest, synthetic_market_data
    from fx_smc_bot.data.audit import audit_series, format_data_audit
    from fx_smc_bot.research.reporting import save_run_artifacts, summary_report
    from fx_smc_bot.utils.logging import setup_logging

    if args.require_quality and not args.data_dir:
        print("error: --require-quality requires --data-dir", file=sys.stderr)
        return 1

    setup_logging(args.log_level)

    config_path = Path(args.config or DEFAULT_CONFIG)
    config = _resolve_config(args.config)
    audit = None
    if args.data_dir:
        data = load_market_data(args.data_dir, config)
        source = f"local data | {args.data_dir}"
        audit = audit_series(data, config, Path(args.data_dir).resolve())
        if audit.status != "ok":
            print(
                f"Data audit: {audit.status.upper()} "
                f"(run 'fx-smc data --data-dir {args.data_dir}' for details)",
                file=sys.stderr,
            )
        if args.require_quality and audit.status != "ok":
            print(format_data_audit(audit), file=sys.stderr)
            print("error: data audit must be ok for this run", file=sys.stderr)
            return 1
    else:
        data = synthetic_market_data(args.bars, seed=args.seed)
        source = f"synthetic demo | {args.bars} bars/pair"

    print(f"Running {source} with {len(data)} pairs...")
    run = run_backtest(config, data)
    print(summary_report(run.result, run.metrics))

    if args.output_dir:
        artifact_dir = save_run_artifacts(
            run.result,
            run.metrics,
            args.output_dir,
            config_dict=config.model_dump(),
            label=args.label,
        )
        manifest = {
            "schema_version": 2,
            "label": args.label,
            "source": "local" if args.data_dir else "synthetic",
            "package_version": __version__,
            "python": platform.python_version(),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "config": {
                "path": str(config_path.resolve()),
                "sha256": _sha256_json(config.model_dump(mode="json")),
            },
            "data": {
                "source": "local" if args.data_dir else "synthetic",
                "directory": (
                    str(Path(args.data_dir).resolve()) if args.data_dir else None
                ),
                "pairs": sorted(pair.value for pair in data),
                "timeframes": {
                    pair.value: series.timeframe.value
                    for pair, series in sorted(data.items(), key=lambda item: item[0].value)
                },
                "bars": {
                    pair.value: len(series)
                    for pair, series in sorted(data.items(), key=lambda item: item[0].value)
                },
                "seed": None if args.data_dir else args.seed,
                "requested_bars": None if args.data_dir else args.bars,
                "fingerprint": _data_fingerprint(data),
            },
            "audit": audit.as_dict() if audit else None,
        }
        (artifact_dir / "manifest.json").write_text(
            json.dumps(manifest, indent=2),
            encoding="utf-8",
        )
        if audit is not None:
            (artifact_dir / "audit.json").write_text(
                json.dumps(audit.as_dict(), indent=2) + "\n",
                encoding="utf-8",
            )
        print(f"Artifacts: {artifact_dir}")
    return 0


def _cmd_dashboard(args: argparse.Namespace) -> int:
    if importlib.util.find_spec("streamlit") is None:
        print(
            'Streamlit is not installed. Run: python -m pip install -e ".[dashboard]"',
            file=sys.stderr,
        )
        return 1

    app = _find_dashboard(args.app)
    if app is None:
        print(
            f"Dashboard app not found: {args.app or DEFAULT_DASHBOARD}",
            file=sys.stderr,
        )
        return 1

    command = [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        str(app),
        "--server.address",
        args.host,
        "--server.port",
        str(args.port),
        "--server.headless",
        "true",
        "--browser.gatherUsageStats",
        "false",
    ]
    print(f"Starting dashboard at http://{args.host}:{args.port} (Ctrl+C to stop)")
    try:
        return subprocess.run(command, check=False).returncode
    except KeyboardInterrupt:
        return 130


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fx-smc",
        description=(
            "Developer CLI for the FX-SMC research framework. "
            "The framework is a research artifact, not a trading signal service."
        ),
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    info = sub.add_parser("info", help="Print the project status and available commands")
    info.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    info.set_defaults(func=_cmd_info)

    doctor = sub.add_parser("doctor", help="Validate Python, config, data and dashboard extras")
    doctor.add_argument("--config", help="YAML config to validate (default: configs/base.yaml)")
    doctor.add_argument("--data-dir", help="Optional market-data directory to inspect")
    doctor.add_argument("--strict", action="store_true", help="Treat warnings as failures")
    doctor.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    doctor.set_defaults(func=_cmd_doctor)

    data = sub.add_parser("data", help="Audit market data quality and coverage")
    data.add_argument("--data-dir", required=True, help="Market-data directory to inspect")
    data.add_argument("--config", help="YAML config (default: configs/base.yaml)")
    data.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    data.add_argument("--output", help="Write the JSON audit to this path")
    data.add_argument("--strict", action="store_true", help="Treat quality warnings as failures")
    data.set_defaults(func=_cmd_data)

    backtest = sub.add_parser("backtest", help="Run one in-process backtest")
    backtest.add_argument("--config", help="YAML config (default: configs/base.yaml if present)")
    source = backtest.add_mutually_exclusive_group()
    source.add_argument("--data-dir", help="Market-data directory; omit for the synthetic demo")
    source.add_argument("--synthetic", action="store_true", help="Use the synthetic demo")
    backtest.add_argument("--bars", type=int, default=500, help="Synthetic bars (default: 500)")
    backtest.add_argument("--seed", type=int, default=42, help="Synthetic seed (default: 42)")
    backtest.add_argument("--output-dir", help="Write run artifacts here")
    backtest.add_argument("--label", default="backtest", help="Artifact label (default: backtest)")
    backtest.add_argument(
        "--require-quality",
        action="store_true",
        help="Fail before the backtest when the data audit is not ok",
    )
    backtest.add_argument("--log-level", default="WARNING", help="Logging level (default: WARNING)")
    backtest.set_defaults(func=_cmd_backtest)

    dashboard = sub.add_parser("dashboard", help="Launch the local Streamlit cockpit")
    dashboard.add_argument("--host", default="127.0.0.1", help="Bind address (default: 127.0.0.1)")
    dashboard.add_argument("--port", type=int, default=8501, help="Port (default: 8501)")
    dashboard.add_argument("--app", help="Alternative dashboard/app.py path")
    dashboard.set_defaults(func=_cmd_dashboard)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
