# Results

Committed research evidence: gate decisions, scorecards, manifests, summaries and
some raw run artifacts. Generated outputs are ignored by git; only reviewed
evidence is tracked.

> Read [../docs/STATUS.md](../docs/STATUS.md) first. The programme is closed
> with no survivor.

---

## What is here

| Path pattern | Content |
|---|---|
| `gate_c2/`, `gate_c3*/`, `gate_c4*/` | Data, execution and event-alpha gates |
| `gate_c5*/` | Validation/hardening gates |
| `gate_c6*/` | Acceptance and data-safety gates |
| `gate_f0*/` | Classical FX factor programmes |
| `gate_q0*/`, `gate_q1*/` | Quant polarity programmes |
| `gate_p0*/`, `gate_p1/` | Strategy-alpha programmes |
| `gate_a0*/` | Alpha discovery A0 iterations |
| `gate_v3f/` | V3 freeze/certification artifacts |
| `gate_v5/`, `gate_v5r/`, `gate_v5r_corrected/` | Structural-model runs and closure |
| `final_promotion_gate/` | Legacy `bos_only_usdjpy` promotion package |

`results/` contains roughly 1,300 tracked files (~41 MB). Raw logs and large
intermediate files are intentionally not all committed; some gates store only the
decision, manifest or summary needed to audit the claim.

## Rules

1. **Results are evidence, not scratch space.** Do not overwrite a historical
   decision to "fix" it.
2. New runs write to a new directory. If a run is a correction, give it a new
   name and cite the original.
3. Keep the decision artifact (`*_decision.json`, `*_FINAL_*`, `*_MEMO*`) next
   to the data it summarizes.
4. Do not add multi-megabyte JSONL logs without a retention decision; prefer a
   summary plus a hash/manifest.
5. `results/*` is gitignored except for this README. Adding a new tracked result
   requires an explicit `git add -f` and review.

## Important discrepancy

`gate_v5r_corrected/v5r_corrected_discovery_decision.json` contains a generated
field:

```json
"next_gate": "MARKET_PIVOT_CRYPTO_PERPETUALS"
```

This is **not** an approved next step. The binding decision is the
[V5R terminal postmortem](../docs/research/fx_alpha_discovery_v5r_corrected/V5R_TERMINAL_POSTMORTEM.md),
which records no next alpha gate. Do not start a crypto-perpetuals programme on
the strength of this field; see
[STATUS.md §4](../docs/STATUS.md#4-important-artifact-discrepancy).

## Finding a result

1. Start from the programme index:
   [../docs/research/README.md](../docs/research/README.md).
2. Open the closure memo for that programme.
3. Use the memo's links to the specific `results/gate_*` directory.
4. If the artifact is not committed, the memo/manifest should say where it lives
   and what hash it has.
