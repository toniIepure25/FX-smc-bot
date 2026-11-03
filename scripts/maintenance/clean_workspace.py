"""Local workspace maintenance: remove test scratch and quarantine stray data.

The script is intentionally conservative:

- dry-run by default; deletion requires ``--apply``;
- only root-level entries matching known temp patterns are considered;
- project directories are protected even if a pattern matches them;
- ``--quarantine-bi5`` moves root-level ``*.bi5`` files into ``var/quarantine``
  rather than deleting them.

Run from the repository root:

    python scripts/maintenance/clean_workspace.py --dry-run
    python scripts/maintenance/clean_workspace.py --apply
    python scripts/maintenance/clean_workspace.py --quarantine-bi5 --apply
"""

from __future__ import annotations

import argparse
import fnmatch
import shutil
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

TEMP_PATTERNS = (
    ".pytest_tmp_*",
    ".tmp",
    ".tmp-*",
    ".codex-test-tmp-*",
    "pytest-*",
    "pytest_*",
)

CACHE_NAMES = (
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".audit_tmp",
)

PROTECTED_NAMES = {
    ".git",
    ".agents",
    ".github",
    "configs",
    "data",
    "deploy",
    "docs",
    "forensics",
    "locks",
    "logs",
    "paper_validation_program",
    "results",
    "scripts",
    "src",
    "tests",
    "tools",
    "var",
}


def is_temp_candidate(name: str) -> bool:
    """Return True when a root-level directory name is known pytest scratch."""
    return any(fnmatch.fnmatchcase(name, pattern) for pattern in TEMP_PATTERNS)


def is_protected(path: Path, root: Path = ROOT) -> bool:
    """Return True when ``path`` is the repository root or a project directory."""
    try:
        relative = path.resolve().relative_to(root.resolve())
    except ValueError:
        return True
    if not relative.parts:
        return True
    return relative.parts[0] in PROTECTED_NAMES


def iter_temp_dirs(root: Path = ROOT) -> list[Path]:
    """Return root-level scratch directories that are safe to remove."""
    return sorted(
        (
            path
            for path in root.iterdir()
            if path.is_dir() and is_temp_candidate(path.name) and not is_protected(path, root)
        ),
        key=lambda item: item.name,
    )


def _remove_readonly(func, path: str, _exc_info) -> None:
    """Best-effort chmod for read-only files before retrying the delete."""
    try:
        Path(path).chmod(0o700)
        func(path)
    except OSError:
        raise


def remove_directory(path: Path) -> bool:
    """Delete ``path``; return True on success, False when Windows ACLs block it."""
    try:
        shutil.rmtree(path, onerror=_remove_readonly)
    except OSError as exc:
        print(f"  FAILED  {path.name}: {exc}")
        return False
    return True


def quarantine_bi5(root: Path = ROOT, apply: bool = False) -> int:
    """Move root-level ``*.bi5`` files to a dated quarantine directory."""
    files = sorted(root.glob("*.bi5"))
    if not files:
        print("No root-level .bi5 files found.")
        return 0

    destination = root / "var" / "quarantine" / f"root-bi5-{date.today():%Y%m%d}"
    total_mb = sum(item.stat().st_size for item in files) / (1024 * 1024)
    print(f"{'Moving' if apply else 'Would move'} {len(files)} .bi5 files ({total_mb:.1f} MB)")
    print(f"  -> {destination}")
    if not apply:
        return 0

    destination.mkdir(parents=True, exist_ok=True)
    moved = 0
    for item in files:
        try:
            shutil.move(str(item), str(destination / item.name))
        except OSError as exc:
            print(f"  FAILED  {item.name}: {exc}")
            continue
        moved += 1

    manifest = destination / "MANIFEST.txt"
    manifest.write_text(
        "\n".join(
            [
                "Root-level .bi5 quarantine",
                f"Moved at: {date.today().isoformat()}",
                f"Files: {moved}",
                f"Size: {total_mb:.2f} MB",
                f"Source: {root}",
                "",
                "Restore with:",
                f'  Get-ChildItem "{destination}" -Filter *.bi5 | Move-Item -Destination "{root}"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"Moved {moved}/{len(files)} files; manifest: {manifest}")
    return moved


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Clean local scratch directories safely.")
    parser.add_argument("--apply", action="store_true", help="Delete entries (default: dry-run).")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Explicit dry-run (the default; accepted for scripts and docs).",
    )
    parser.add_argument(
        "--include-cache",
        action="store_true",
        help="Also remove .pytest_cache, .mypy_cache, .ruff_cache and .audit_tmp.",
    )
    parser.add_argument(
        "--quarantine-bi5",
        action="store_true",
        help="Move root-level *.bi5 files to var/quarantine instead of leaving them.",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=ROOT,
        help=argparse.SUPPRESS,
    )
    args = parser.parse_args(argv)

    print(f"Repository: {args.root}")
    print("Mode:", "APPLY" if args.apply else "DRY-RUN")

    targets = iter_temp_dirs(args.root)
    if args.include_cache:
        targets.extend(
            path
            for path in args.root.iterdir()
            if path.is_dir() and path.name in CACHE_NAMES and not is_protected(path, args.root)
        )
        targets = sorted(set(targets), key=lambda item: item.name)

    if not targets:
        print("No scratch directories found.")
    else:
        print(f"Found {len(targets)} scratch director{'y' if len(targets) == 1 else 'ies'}:")
        failures: list[Path] = []
        for path in targets:
            if not args.apply:
                print(f"  would remove  {path.name}")
                continue
            print(f"  removing      {path.name}")
            if not remove_directory(path):
                failures.append(path)
        if args.apply and failures:
            log_dir = args.root / "var" / "quarantine"
            log_dir.mkdir(parents=True, exist_ok=True)
            log_path = log_dir / f"cleanup-failures-{date.today():%Y%m%d}.txt"
            log_path.write_text(
                "\n".join(
                    [
                        f"# Scratch directories that could not be removed on {date.today().isoformat()}.",
                        "# Reason: Windows ACLs deny listing/delete for the current user.",
                        "# These entries are ignored by git and harmless.",
                        "",
                        *(path.name for path in failures),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            print(f"Completed with {len(failures)} failure(s) blocked by filesystem ACLs.")
            print(f"Failure list: {log_path}")

    if args.quarantine_bi5:
        quarantine_bi5(args.root, apply=args.apply)

    return 0


if __name__ == "__main__":
    sys.exit(main())
