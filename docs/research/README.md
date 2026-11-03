# Research Archive

This directory contains the research record of the FX-smc-bot programme: gate
documents, pre-registrations, protocols, data certifications, decision memos and
postmortems. It is an **archive**, not a live notebook.

**Current status:** `CURRENT_DATA_ALPHA_SEARCH_EXHAUSTED` — see
[../STATUS.md](../STATUS.md).

---

## How to read the archive

1. Read [../STATUS.md](../STATUS.md) first.
2. Read the closure memo for the programme you care about (table below).
3. Only then open individual gate documents. They assume the protocol context
   and are easy to misread in isolation.
4. Treat every file as immutable evidence. Do not update old decisions; write a
   new document that cites them.

File-name conventions:

- `GATE_*` — gate protocol, decision memo, audit or blocker analysis;
- `*_FINAL_DECISION_MEMO.md` — closure of a programme;
- `*_POSTMORTEM.md` — post-outcome engineering/scientific review;
- `*_PROTOCOL*` / `*_FREEZE*` — pre-registered rules and frozen inputs;
- `*_MANIFEST*` — data/artifact inventory and hashes;
- `CLASSICAL_*`, `QUANT_*`, `STRATEGY_*`, `A0*`, `V*` — programme families.

## Programme index

| Programme | Directory | Scope | Closure |
|---|---|---|---|
| Classical FX factors | [classical_fx_factors/](classical_fx_factors/) | Carry, value, momentum, volatility factors on FX | [F0 final memo](classical_fx_factors/F0_FINAL_DECISION_MEMO.md) |
| Classical FX factors v2 | [classical_fx_factors_v2/](classical_fx_factors_v2/) | Hardened factor replication and cost-aware follow-ups | [F0RPE2ER final memo](classical_fx_factors_v2/F0RPE2ER_FINAL_DECISION_MEMO.md) |
| Strategy alpha | [strategy_alpha/](strategy_alpha/) | Strategy-level alpha and execution variants | [P0 final memo](strategy_alpha/P0_FINAL_DECISION_MEMO.md) |
| Quant polarity | [quant_polarity/](quant_polarity/) | Polarity/conditioning experiments | [Q0 final memo](quant_polarity/Q0_FINAL_DECISION_MEMO.md) |
| Quant polarity v2 | [quant_polarity_v2/](quant_polarity_v2/) | Q0R/Q1 hardening and closure | [Q1 final memo](quant_polarity_v2/Q1_FINAL_DECISION_MEMO.md) |
| Alpha discovery A0 | [fx_alpha_discovery/](fx_alpha_discovery/) | Broad alpha discovery and stop-before-2018 gate | [A0 final memo](fx_alpha_discovery/A0_FINAL_DECISION_MEMO.md) |
| Alpha discovery v3 | [fx_alpha_discovery_v3/](fx_alpha_discovery_v3/) | 1,388-candidate broad search; data gates | [V3 programme review](fx_alpha_discovery_v3/V3_PROGRAM_REVIEW.md) |
| Alpha discovery v4 | [fx_alpha_discovery_v4/](fx_alpha_discovery_v4/) | CME FX futures L2 pilot design | Never executed — no paid data |
| Alpha discovery v5 | [fx_alpha_discovery_v5/](fx_alpha_discovery_v5/) | First structural-model attempt | [V5 forensics](fx_alpha_discovery_v5/V5_ENGINEERING_FORENSICS.md) · [adjudication](fx_alpha_discovery_v5/V5_INTEGRITY_ADJUDICATION.md) |
| Alpha discovery v5r corrected | [fx_alpha_discovery_v5r_corrected/](fx_alpha_discovery_v5r_corrected/) | True structural models + protocol-conformance rerun | [Terminal postmortem](fx_alpha_discovery_v5r_corrected/V5R_TERMINAL_POSTMORTEM.md) |

## Gate-level documents

The top level of `docs/research/` contains the earlier gate line (C2–C6) and
cross-programme acceptance documents. Representative entry points:

| Document | Content |
|---|---|
| [GATE_C2_DECISION_MEMO.md](GATE_C2_DECISION_MEMO.md) | Execution/data gate C2 |
| [GATE_C2_DATA_ACQUISITION_GUIDE.md](GATE_C2_DATA_ACQUISITION_GUIDE.md) | Data acquisition protocol for C2 |
| [GATE_C3FR_2019_CERTIFICATION.md](GATE_C3FR_2019_CERTIFICATION.md) | 2019 data certification |
| [GATE_C3FCRSF_FINAL_DECISION_MEMO.md](GATE_C3FCRSF_FINAL_DECISION_MEMO.md) | Tick/data freeze decision |
| [ACCEPTANCE_RESEARCH_PACKAGE_INDEX.md](ACCEPTANCE_RESEARCH_PACKAGE_INDEX.md) | Earlier acceptance package index |
| [ACCEPTANCE_RESEARCH_LESSONS.md](ACCEPTANCE_RESEARCH_LESSONS.md) | Cross-gate lessons |
| [ACCEPTANCE_RESEARCH_METHODS.md](ACCEPTANCE_RESEARCH_METHODS.md) | Cross-gate methods |

## Reading the result

- **Do not** interpret a single positive candidate as alpha. The programmes used
  multiplicity corrections and pre-holdout gates precisely because single
  candidates are noisy.
- **Do not** treat a generated `next_gate` field in a JSON artifact as a
  decision. The postmortems are binding; see
  [STATUS.md](../STATUS.md#4-important-artifact-discrepancy).
- **Do not** access the 2018+ holdout to check a hypothesis from this archive.

## Adding new research

New work does **not** belong in these directories. Create a new programme
directory with:

1. a written hypothesis and economic rationale;
2. a data contract and cost preflight;
3. a pre-registered candidate list and gate definitions;
4. a sealed holdout that has never been inspected;
5. a closure memo written regardless of outcome.

The decision to start belongs in [../ROADMAP.md](../ROADMAP.md) and, once made,
in [../STATUS.md](../STATUS.md).
