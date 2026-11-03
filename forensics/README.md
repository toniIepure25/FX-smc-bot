# Forensics

Preserved code and artifacts used to audit past research runs. They are evidence,
not production code.

| Path | Purpose |
|---|---|
| `v5/original_run_v5_discovery.py` | Exact copy of the runner used for the V5 discovery attempt, kept for the V5 engineering forensics |

Rules:

- Do not edit files here; they are referenced by forensic reports.
- Do not execute them as part of normal development. They may depend on data
  layouts and settings that no longer exist.
- If a new forensic audit needs a changed runner, add a new file and cite the
  original.

See [../docs/research/fx_alpha_discovery_v5/V5_ENGINEERING_FORENSICS.md](../docs/research/fx_alpha_discovery_v5/V5_ENGINEERING_FORENSICS.md)
and [../docs/STATUS.md](../docs/STATUS.md).
