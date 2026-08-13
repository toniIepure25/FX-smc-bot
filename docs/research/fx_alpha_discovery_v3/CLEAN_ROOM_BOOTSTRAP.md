# V3 Clean-Room Bootstrap (Apple M5, arm64)

Reproduces the V3 research environment on a clean Apple Silicon Mac and verifies the V2
cross-machine scientific reproduction. No 2018+ data is touched.

## Machine (captured)

| Field | Value |
| --- | --- |
| macOS | 26.5.2 (build 25F84) |
| Model / CPU | Mac17,4 / Apple M5 |
| Architecture | arm64 (native; no Rosetta) |
| Cores | 10 logical / 10 physical |
| Unified memory | 16 GiB |
| Free disk (at bootstrap) | ~365 GiB |

Full machine-readable capture:
[`results/gate_v3f/environment_profile.json`](../../../results/gate_v3f/environment_profile.json).

## Toolchain

The clean machine had only system Python 3.9.6, but the repo requires ≥3.10. A native arm64
toolchain is installed in **user space** (no admin password, nothing in system directories):

```bash
# 1. uv (user-space); corporate TLS interception -> use the macOS trust store
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"
export UV_SYSTEM_CERTS=1

# 2. native arm64 CPython 3.12 + venv + deps
uv python install 3.12
uv venv --python 3.12 .venv
uv pip install -e ".[dev]"

# 3. hash-pinned lock (this improves the previously lock-free project)
uv pip compile pyproject.toml --extra dev --generate-hashes --universal -o requirements.lock
```

`UV_SYSTEM_CERTS=1` is required because the network path performs TLS interception; uv's
bundled certificate store rejects the corporate root CA, while the macOS keychain trusts it.

## Scientific stack (verified)

CPython 3.12.13 (arm64, `HOST_GNU_TYPE=aarch64-apple-darwin`), NumPy 2.5.2 on **Apple
Accelerate** BLAS/LAPACK (NEON ASIMDHP/ASIMDDP), pandas 2.3.3, polars 1.43.2, scipy 1.18.0,
scikit-learn 1.9.0, pyarrow 25.0.1. Dependency lock digest recorded in the freeze manifest.

## Cross-machine V2 reproduction (verified)

```bash
.venv/bin/python scripts/v3/capture_environment.py
# -> arm64_native: True | BLAS: accelerate
# -> V2 digest match: True   (A0R5 materialization_digest 4ead4048… reproduced byte-identically)
```

Plus the V2 golden-kernel/dry-run regression: `pytest tests/test_gate_a0r4` → 244 passed, 1
skipped on this Accelerate/arm64 stack. Byte-identical scientific identity + float
reproduction within frozen ULP tolerances ⇒ the project is independent of the old workstation.

## Rebuild + freeze verification

```bash
export OMP_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1   # avoid BLAS oversubscription
.venv/bin/python scripts/v3/capture_environment.py
.venv/bin/python scripts/v3/run_dry_run.py
.venv/bin/python scripts/v3/run_benchmarks.py
.venv/bin/python scripts/v3/build_v3_freeze.py       # -> verdict: V3_ALPHA_DISCOVERY_READY (35/35)
.venv/bin/python -m pytest tests/test_gate_v3f tests/test_gate_a0r4 -q
```

## Memory / concurrency (M5, 16 GiB)

Peak RSS for representative components ≈ 0.24 GiB; every component runs in <0.13 s on seeded
synthetic data
([`mac_performance_profile.json`](../../../results/gate_v3f/mac_performance_profile.json)).
Recommended heavy-worker concurrency: **6** (RAM-bound at ~2 GiB/worker with 4 GiB reserved,
CPU-bound at cores−2), BLAS threads = 1 per worker, swap never used as a normal strategy.
