# var/ — local scratch

Ignored by git. Everything here can be deleted without affecting tracked code or
evidence, except the quarantine directories described below.

| Directory | Purpose |
|---|---|
| `cache/` | Local caches (pytest cache, tool caches) |
| `quarantine/` | Preserved local artifacts that are not part of the repository |
| `smoke/` | Output of the README synthetic smoke test |

## Quarantine contents

| Path | What it is |
|---|---|
| `quarantine/root-bi5-20261103/` | 7,721 stray `.bi5` files (87 MB) moved out of the repository root; see `MANIFEST.txt` |
| `quarantine/audit-2026-07/` | Four JSON audit logs recovered from the old `.audit_tmp/` cache |
| `quarantine/cleanup-failures-20261103.txt` | Root-level temp directories that could not be removed because Windows ACLs deny access |

The failed directories are pytest scratch directories created by earlier runs
under a different security context. They are harmless but cannot be deleted or
renamed by the current user. Remove them from an elevated shell if the ACLs can be
repaired, or leave them; they are ignored by git.

## Rules

- Never commit files from `var/`.
- Do not put research evidence here; tracked evidence belongs in `results/`.
- The synthetic smoke output is disposable; delete `var/smoke/` after testing.
- `scripts/maintenance/clean_workspace.py` defaults to dry-run; use `--apply`
  only after reviewing its output.
