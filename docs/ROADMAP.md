# Roadmap

**Status of this document:** proposals, not approved work. The research programme
itself is closed; see [STATUS.md](STATUS.md). The items below improve the
repository as an engineering asset and prepare a possible future programme.

Priority order is deliberate: trust in the code and documentation comes before
new research. Any new alpha work is blocked until a separate decision is recorded.

---

## P0 — Completed in the current cleanup

These are done and should not be re-litigated:

- canonical status page (`docs/STATUS.md`) and documentation index;
- root-level workspace cleanup (stray `.bi5`, pytest temp trees, caches);
- pytest collection fix (`--import-mode=importlib`) and portable temp root;
- `F821` undefined-name fixes;
- run-artifact export fix for the slots-based `PerformanceSummary`;
- host-independent Q0 storage-budget protocol test;
- README rewrite and area indexes (`scripts/`, `results/`, `data/`, `var/`,
  `forensics/`, `paper_validation_program/`);
- `.gitignore` / `.dockerignore` hygiene;
- `scripts/maintenance/clean_workspace.py` with dry-run default;
- local Streamlit research cockpit (`dashboard/`), with tested data preparation
  and a price/position/equity UI.

## P1 — Make the codebase trustworthy

**Goal:** a new contributor can run the suite and the linter, and CI can enforce
both without surprises.

### P1.1 Lint and type baseline
- Current Ruff baseline: about 367 findings in `src/`, about 590 in `src` + `tests`.
- Fix the core packages first: `alpha`, `backtesting`, `data`, `execution`,
  `live`, `ml`, `portfolio`, `risk`, `structure`, `utils`.
- Use auto-fix (`ruff check --fix`) only on non-frozen packages, then review the
  diff. Do not mass-rewrite `research/v3`, `research/v5r` or `scripts/run_gate_*`;
  those encode frozen protocols.
- Add per-file ignores only with a comment explaining the frozen identifier or
  historical artifact.
- Add a `mypy` configuration with a documented baseline. Do not claim strict
  typing until the baseline is zero.

**Acceptance:** `ruff check src/fx_smc_bot` passes (excluding documented frozen
paths), and `mypy src/fx_smc_bot` has a non-increasing, recorded error count.

### P1.2 CI
- GitHub Actions matrix: Python 3.10, 3.11, 3.12 on Ubuntu.
- Jobs: `pytest -q`, `ruff check` (core scope), `ruff check --select F821`,
  documentation link check.
- Cache `pip`/`uv`; keep total runtime under ~15 minutes.
- Do not add a badge until the workflow is green on the default branch.

**Acceptance:** a pull request runs the suite and lint automatically; a red
workflow blocks merge.

### P1.3 Coverage where it matters
- Add `pytest-cov` and measure `src/fx_smc_bot/{risk,execution,data,backtesting}`.
- Set targets per module based on the measured baseline, not a global 80% target.
- Add regression tests for any bug found during cleanup.

**Acceptance:** coverage is reported in CI; the critical modules do not regress.

## P2 — Reproducibility, packaging and operations

### P2.1 Reproducibility guide
- Add `docs/REPRODUCIBILITY.md` with exact commands for:
  - regenerating the synthetic smoke dataset;
  - running a single backtest;
  - running the V3/V5R programmes from frozen configs;
  - verifying artifact hashes and expected file layout.
- Record runtime, Python version and data digest for each recipe.
- Verify at least one recipe end-to-end on a clean environment.

### P2.2 Packaging
- Add console entry points in `pyproject.toml`:
  - `fx-smc-data`
  - `fx-smc-backtest`
  - `fx-smc-campaign`
  - `fx-smc-paper`
- Make the scripts thin wrappers over library functions so Docker and CI do not
  depend on repository-relative `scripts/` paths.
- Add a `Makefile` and a PowerShell `tasks.ps1` with `setup`, `test`, `lint`,
  `clean`, `smoke`.
- Decide whether to keep `requirements.lock` (current) or move to `uv.lock`;
  document the regeneration command either way.

### P2.3 Docker and forward service
- Reconcile `.env.example`, `docker-compose.yml` and the actual
  `run_live_forward_service.py --mode` choices. The current docs and code do not
  agree on `oanda` / `file_watch` / `live` / `replay`.
- Run the Docker smoke test in CI or in a documented manual check.
- Pin the base image by digest, run as a non-root user, and keep the health check.
- Mark the service clearly as legacy and unvalidated in the image labels.

### P2.4 Repository size
- `results/` contains ~41 MB of committed evidence; `data/` is ~7.7 GB locally.
- Decide whether future large artifacts belong in Git LFS or external storage.
- Do not rewrite history to shrink the repository; add a retention policy for
  new artifacts instead.

## P3 — Research decision (blocked until P1/P2 are healthy)

The current programme is closed. Pick exactly one path and record the decision in
`docs/STATUS.md` or a new decision memo.

### Option A — New data class (L2 / order flow)
- **Hypothesis:** short-horizon liquidity/order-flow information not present in
  M1 OHLCV.
- **Cost:** paid market data, new ingestion, new execution model, new protocol.
- **Prerequisite:** data-cost preflight (V4 already showed this can block the
  programme) and a pre-registered candidate list.

### Option B — New market (e.g. crypto perpetuals)
- **Hypothesis:** structural effects may differ in a 24/7, retail-heavy market.
- **Cost:** new data, new session model, new cost/funding model, new protocol.
- **Prerequisite:** explicit acknowledgement that FX results do not transfer and
  that the generated `next_gate` field is not an approval.

### Option C — Archive
- **Hypothesis:** the framework is the deliverable; further alpha search has poor
  expected value.
- **Action:** freeze the repository, keep the docs and tests runnable, move large
  artifacts to cold storage.
- **Benefit:** lowest cost, preserves the negative result and the engineering
  lessons.

### Option D — Legacy paper programme
- Only if a separate review concludes the 2026-04 evidence is still valid.
- The programme was designed but no sessions were recorded (see
  `paper_validation_program/`).
- It must not be used to bypass the closed V1–V5R result.

**Decision rule:** no new alpha run starts without (1) a written hypothesis,
(2) a new data/market class, (3) a pre-registered protocol, (4) a sealed holdout
that has never been inspected, and (5) an explicit budget for data and compute.

## Suggested sequence

1. P1.1 lint/type baseline (1–2 days).
2. P1.2 CI + P1.3 coverage (1–2 days).
3. P2.1 reproducibility guide (1 day).
4. P2.2 packaging + task runner (1–2 days).
5. P2.3 Docker/ops reconciliation (1 day).
6. P3 decision memo (half day, plus data-cost preflight if Option A).

Do not start P3 before P1 is green: a new programme on an untrusted test suite
would repeat the V5 failure mode.

## Out of scope

- Re-running V1–V5R with tweaked parameters.
- Signal inversion or candidate rescue.
- Using the 2018+ holdout to "confirm" anything.
- Live trading based on legacy results.
- Rewriting research evidence to make the result look better.
