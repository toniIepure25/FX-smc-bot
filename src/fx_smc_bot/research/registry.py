"""Experiment registry: track, store, and compare experiment runs.

Each run gets a unique ID, config snapshot, and result metadata.
The registry persists as a JSON file alongside experiment artifacts.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class RunRecord:
    run_id: str
    label: str
    config_hash: str
    timestamp: str
    status: str = "pending"
    metrics: dict[str, Any] = field(default_factory=dict)
    artifact_dir: str = ""
    tags: list[str] = field(default_factory=list)
    notes: str = ""
    duration_seconds: float = 0.0
    data_fingerprint: str = ""
    code_version: str = ""
    assumptions: dict[str, Any] = field(default_factory=dict)
    gate_result: dict[str, Any] = field(default_factory=dict)
    warning_flags: list[str] = field(default_factory=list)


class ExperimentRegistry:
    """Persistent registry of experiment runs."""

    def __init__(self, registry_path: Path | str) -> None:
        self._path = Path(registry_path)
        self._runs: list[RunRecord] = []
        if self._path.exists():
            self._load()

    def _load(self) -> None:
        with open(self._path) as f:
            data = json.load(f)
        self._runs = [RunRecord(**r) for r in data.get("runs", [])]

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        data = {"runs": [asdict(r) for r in self._runs]}
        with open(self._path, "w") as f:
            json.dump(data, f, indent=2)

    def create_run(
        self,
        label: str,
        config_dict: dict[str, Any],
        tags: list[str] | None = None,
        notes: str = "",
    ) -> RunRecord:
        config_json = json.dumps(config_dict, sort_keys=True, default=str)
        config_hash = hashlib.sha256(config_json.encode()).hexdigest()[:12]
        ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        run_id = f"{label}_{ts}_{config_hash[:6]}"

        record = RunRecord(
            run_id=run_id, label=label, config_hash=config_hash,
            timestamp=ts, tags=tags or [], notes=notes,
        )
        self._runs.append(record)
        self._save()
        logger.info("Created run %s", run_id)
        return record

    def complete_run(
        self,
        run_id: str,
        metrics: dict[str, Any],
        artifact_dir: str = "",
        duration_seconds: float = 0.0,
    ) -> None:
        for run in self._runs:
            if run.run_id == run_id:
                run.status = "completed"
                run.metrics = metrics
                run.artifact_dir = artifact_dir
                run.duration_seconds = duration_seconds
                break
        self._save()

    def fail_run(self, run_id: str, error: str = "") -> None:
        for run in self._runs:
            if run.run_id == run_id:
                run.status = "failed"
                run.notes = error
                break
        self._save()

    def get_run(self, run_id: str) -> RunRecord | None:
        for run in self._runs:
            if run.run_id == run_id:
                return run
        return None

    def list_runs(
        self,
        label: str | None = None,
        status: str | None = None,
        tag: str | None = None,
    ) -> list[RunRecord]:
        results = self._runs
        if label:
            results = [r for r in results if r.label == label]
        if status:
            results = [r for r in results if r.status == status]
        if tag:
            results = [r for r in results if tag in r.tags]
        return results

    def summary(self) -> str:
        lines = [f"Registry: {self._path}", f"Total runs: {len(self._runs)}"]
        for r in self._runs[-10:]:
            sharpe = r.metrics.get("sharpe_ratio", "N/A")
            trades = r.metrics.get("total_trades", "N/A")
            lines.append(
                f"  {r.run_id:40s}  status={r.status:10s}  "
                f"sharpe={sharpe}  trades={trades}"
            )
        return "\n".join(lines)
