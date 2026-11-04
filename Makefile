PY ?= python

.PHONY: install lint test test-fast doctor smoke dashboard

install:
	$(PY) -m pip install -e ".[dev,dashboard]"

lint:
	$(PY) -m ruff check src/fx_smc_bot --exclude src/fx_smc_bot/research
	$(PY) -m ruff check tests/test_cli.py tests/test_dashboard tests/test_backtesting/test_runner.py

test:
	$(PY) -m pytest -q --no-header

test-fast:
	$(PY) -m pytest -q --no-header tests/test_domain.py tests/test_cli.py \
		tests/test_structure tests/test_backtesting tests/test_risk \
		tests/test_alpha tests/test_dashboard

doctor:
	$(PY) -m fx_smc_bot doctor --config configs/base.yaml --strict

smoke:
	$(PY) -m fx_smc_bot backtest --synthetic --bars 500 --log-level WARNING

dashboard:
	$(PY) -m fx_smc_bot dashboard
