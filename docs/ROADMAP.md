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
  and a price/position/equity UI;
- shared `backtesting.runner` used by the dashboard and CLI (one synthetic/load/run
  path instead of duplicated implementations);
- `fx-smc` developer CLI (`info`, `doctor`, `backtest`, `dashboard`);
- non-research source is Ruff-clean; `research` remains intentionally excluded;
- GitHub Actions CI (lint, `doctor --strict`, full pytest) and local
  `Makefile` / `tasks.ps1` wrappers.

## P1 — Make the codebase trustworthy

**Goal:** a new contributor can run the suite and the linter, and CI can enforce
both without surprises.

### P1.1 Lint and type baseline
- **Current state:** `ruff check src/fx_smc_bot --exclude src/fx_smc_bot/research`
  passes. The frozen `research` tree and most `tests/`/`scripts/` remain outside
  the style gate.
- Keep auto-fix (`ruff check --fix`) restricted to non-frozen packages, then
  review the diff. Do not mass-rewrite `research/v3`, `research/v5r` or
  `scripts/run_gate_*`; those encode frozen protocols.
- Add per-file ignores only with a comment explaining the frozen identifier or
  historical artifact.
- Add a `mypy` configuration with a documented baseline. Do not claim strict
  typing until the baseline is zero.

**Acceptance:** the non-research source remains Ruff-clean in CI, and `mypy
src/fx_smc_bot` has a non-increasing, recorded error count. *(Lint half done;
mypy still open.)*

### P1.2 CI
- GitHub Actions matrix: Python 3.10 and 3.12 on Ubuntu.
- Jobs/steps: full `pytest -q`, non-research `ruff check`, `fx-smc doctor
  --strict`, dependency caching and concurrency cancellation.
- Do not add a badge until the workflow is green on the default branch.
- Future: documentation link check. *(Coverage reporting added: CI uploads
  `coverage.xml` for each matrix entry.)*
- **Done:** `fx-smc data` audits configured-pair coverage, execution-timeframe
  fallback and data quality; the same audit feeds `doctor --data-dir` and can gate
  a local run with `--strict` or `backtest --require-quality`.
- **Done:** manifest schema 2 records the config SHA-256, exact data fingerprint
  and the local audit; local runs also write `audit.json`.
- **Done:** CI has wheel/`twine`/installed-entry-point validation and a Docker
  build plus unprivileged synthetic smoke test.

**Acceptance:** a pull request runs the suite, lint, package validation and
Docker smoke automatically; a red workflow blocks merge. *(Workflow extended;
needs a first green run on the remote.)*

### P1.3 Coverage where it matters
- **Done:** `pytest-cov` is a dev dependency, `coverage` is configured in
  `pyproject.toml`, CI writes a terminal report plus `coverage.xml`, and
  `make coverage` / `.\tasks.ps1 coverage` run it locally.
- Still open: set per-module targets for `risk`, `execution`, `data` and
  `backtesting` from a recorded baseline, and fail CI below those targets.
- Add regression tests for any bug found during cleanup.

**Acceptance:** coverage is reported in CI; the critical modules do not regress.
*(Reporting done; thresholds still open.)*

## P2 — Reproducibility, packaging and operations

### P2.1 Reproducibility guide
- **Done:** `docs/REPRODUCIBILITY.md` covers clean-environment setup, the
  deterministic synthetic run, the file-backed loader path, tests/CI parity,
  artifact hashing and the immutable-evidence rules. Manifest schema 2 adds the
  config hash and a fingerprint of the exact timestamp/OHLCV arrays.
- Still open: add the exact frozen V3/V5R programme commands and record a
  data digest for each recipe.
- Verify at least one recipe end-to-end on a clean environment (the synthetic
  command is exercised locally, not yet on a fresh machine).

### P2.2 Packaging
- **Done:** one `fx-smc` console entry point covering `info`, `doctor`, `data`,
  `backtest` and `dashboard`, plus `python -m fx_smc_bot` as a PATH-free fallback.
  Local `Makefile` and PowerShell `tasks.ps1` wrappers cover install, lint, test,
  doctor, coverage, smoke and package build/check.
- **Done:** CI builds the sdist and wheel, runs `twine check`, force-installs the
  wheel without dependencies and validates `fx-smc info` plus `doctor --strict`.
- Still open: separate `fx-smc-data`, `fx-smc-backtest`, `fx-smc-campaign` and
  `fx-smc-paper` commands.
- Make the remaining scripts thin wrappers over library functions so Docker and
  CI do not depend on repository-relative `scripts/` paths. The smoke backtest
  already shares `backtesting.runner`; the frozen research-gate runners should
  stay as auditable protocol entry points.
- Decide whether to keep `requirements.lock` (current) or move to `uv.lock`;
  document the regeneration command either way.

### P2.3 Docker and forward service
- **Done:** `.env.example`, `docker-compose.yml` and
  `run_live_forward_service.py` now agree on `live` / `replay`; OANDA
  credentials are marked as optional legacy inputs, and the image runs as an
  unprivileged user with dropped capabilities, a normal (non-editable) install
  and legacy/unvalidated image labels.
- **Done:** CI builds the image, asserts uid `10001`, runs `info` and executes a
  synthetic backtest inside the container.
- Still open: pin the base image by digest. No digest has been resolved and
  verified from this environment, so do not invent one.

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

1. P1.1 remaining mypy baseline and frozen-path policy (1 day). *(Ruff half done.)*
2. P1.2 first green CI run + P1.3 coverage thresholds (1–2 days). *(Workflow
   extended with package and Docker jobs.)*
3. P2.1 reproducibility guide (1 day).
4. P2.2 additional console entry points and script thinning (1–2 days).
   *(`fx-smc`, Makefile, tasks.ps1 and CI wheel validation done.)*
5. P2.3 Docker/ops reconciliation (1 day). *(Docker smoke done; digest open.)*
6. P3 decision memo (half day, plus data-cost preflight if Option A).

Do not start P3 before P1 is green: a new programme on an untrusted test suite
would repeat the V5 failure mode.

## Out of scope

- Re-running V1–V5R with tweaked parameters.
- Signal inversion or candidate rescue.
- Using the 2018+ holdout to "confirm" anything.
- Live trading based on legacy results.
- Rewriting research evidence to make the result look better.
