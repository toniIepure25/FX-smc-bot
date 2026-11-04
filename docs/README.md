# Documentation Index

Start with the status, then choose the track that matches your task.

## Start here

| Document | Read it when |
|---|---|
| [../README.md](../README.md) | You are opening the repository for the first time |
| [STATUS.md](STATUS.md) | You need the authoritative current status, verdict or holdout rules |
| [CLI.md](CLI.md) | You want the `fx-smc` commands for validation, smoke runs and the dashboard |
| [ARCHITECTURE.md](ARCHITECTURE.md) | You need the module map and design decisions |
| [ROADMAP.md](ROADMAP.md) | You want to improve the repository or decide what happens next |

## Framework guides

These describe the reusable framework. They predate the 2026 V1–V5R programme
and remain useful, but they are not evidence of an edge.

| Document | Content |
|---|---|
| [DATA_GUIDE.md](DATA_GUIDE.md) | Data sources, canonical schema, ingestion and inspection |
| [RISK_MODEL.md](RISK_MODEL.md) | Position sizing, constraints, exposure budgeting and lockouts |
| [RESEARCH_METHODOLOGY.md](RESEARCH_METHODOLOGY.md) | Ablation, walk-forward and robustness methodology |
| [VALIDATION_GUIDE.md](VALIDATION_GUIDE.md) | Out-of-sample discipline and go/no-go criteria |
| [CANDIDATE_SELECTION_GUIDE.md](CANDIDATE_SELECTION_GUIDE.md) | Composite scorecard and champion selection |
| [PROMOTION_WORKFLOW.md](PROMOTION_WORKFLOW.md) | Research → candidate → paper → approved state machine |
| [HOLDOUT_POLICY.md](HOLDOUT_POLICY.md) | Holdout sealing and access rules |
| [PAPER_TRADING_GUIDE.md](PAPER_TRADING_GUIDE.md) | Paper broker, journal and operational controls |
| [DASHBOARD.md](DASHBOARD.md) | Local Streamlit research dashboard: charts, positions, attribution, exports |
| [PAPER_CAMPAIGN_GUIDE.md](PAPER_CAMPAIGN_GUIDE.md) | Paper campaign setup and reviews |
| [EXPERIMENT_PLAYBOOK.md](EXPERIMENT_PLAYBOOK.md) | Step-by-step experiment recipes |

## Operations and deployment

| Document | Content |
|---|---|
| [../deploy/docs/COMPLETE_DEPLOYMENT_GUIDE.md](../deploy/docs/COMPLETE_DEPLOYMENT_GUIDE.md) | End-to-end VPS/Docker deployment |
| [../deploy/docs/forward_paper_stack_overview.md](../deploy/docs/forward_paper_stack_overview.md) | Forward paper stack components |
| [../deploy/docs/operator_playbook.md](../deploy/docs/operator_playbook.md) | Day-to-day operation |
| [../deploy/docs/crash_and_recovery_playbook.md](../deploy/docs/crash_and_recovery_playbook.md) | Crash and resume procedures |
| [../deploy/docs/final_vps_trial_readiness_verdict.md](../deploy/docs/final_vps_trial_readiness_verdict.md) | Legacy readiness verdict |
| [../paper_validation_program/README.md](../paper_validation_program/README.md) | Legacy paper programme (not executed) |

## Research archive

The research record is large (300+ documents). Use the archive index rather than
reading individual gate files in isolation.

| Document | Content |
|---|---|
| [research/README.md](research/README.md) | Programme index, verdicts and reading order |
| [research/ACCEPTANCE_RESEARCH_PACKAGE_INDEX.md](research/ACCEPTANCE_RESEARCH_PACKAGE_INDEX.md) | Earlier acceptance package index |
| [research/fx_alpha_discovery_v5r_corrected/V5R_TERMINAL_POSTMORTEM.md](research/fx_alpha_discovery_v5r_corrected/V5R_TERMINAL_POSTMORTEM.md) | Binding closure of the 2026 programme |
| [research/fx_alpha_discovery_v3/V3_PROGRAM_REVIEW.md](research/fx_alpha_discovery_v3/V3_PROGRAM_REVIEW.md) | Broad-search closure |

Research documents follow these conventions:

- `docs/research/` contains **immutable evidence**: decisions, protocols,
  manifests and postmortems. Do not rewrite them retroactively.
- New work gets a new directory and a new pre-registration; it does not edit old
  gate documents.
- Generated result artifacts live under `results/`; see
  [../results/README.md](../results/README.md).

## Historical handoffs

These documents describe earlier project states. They are kept for lineage and
are **superseded** by [STATUS.md](STATUS.md).

| Document | Historical state |
|---|---|
| [PROJECT_CONTEXT_FOR_LLMS.md](PROJECT_CONTEXT_FOR_LLMS.md) | 2026-04 context around the `bos_only_usdjpy` champion |
| [LLM_HANDOFF_SUMMARY.md](LLM_HANDOFF_SUMMARY.md) | 2026-04 quick handoff for the same programme |

## Documentation rules

1. Update [STATUS.md](STATUS.md) when the project state changes; do not fork a
   second status document.
2. Date new documents and label them `CURRENT`, `HISTORICAL` or `EVIDENCE`.
3. Link to `results/` artifacts instead of duplicating their numbers.
4. Keep research documents immutable; corrections are new documents that cite
   the original.
