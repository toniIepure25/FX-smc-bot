param(
    [ValidateSet("install", "lint", "test", "test-fast", "coverage", "doctor", "smoke", "dashboard")]
    [string]$Task = "test"
)

$ErrorActionPreference = "Stop"
$python = if ($env:PYTHON) { $env:PYTHON } else { "python" }

function Invoke-Step {
    param([string]$Description, [scriptblock]$Command)
    Write-Host "==> $Description" -ForegroundColor Cyan
    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "$Description failed with exit code $LASTEXITCODE"
    }
}

switch ($Task) {
    "install" {
        Invoke-Step "Installing project and extras" {
            & $python -m pip install -e ".[dev,dashboard]"
        }
    }
    "lint" {
        Invoke-Step "Linting non-research source" {
            & $python -m ruff check src/fx_smc_bot --exclude src/fx_smc_bot/research
        }
        Invoke-Step "Linting dashboard and CLI tests" {
            & $python -m ruff check dashboard/app.py tests/test_cli.py `
                tests/test_data/test_audit.py tests/test_dashboard `
                tests/test_backtesting/test_runner.py
        }
    }
    "test" {
        Invoke-Step "Running the full test suite" {
            & $python -m pytest -q --no-header
        }
    }
    "test-fast" {
        Invoke-Step "Running the fast core suite" {
            & $python -m pytest -q --no-header tests/test_domain.py tests/test_cli.py `
                tests/test_structure tests/test_backtesting tests/test_risk `
                tests/test_alpha tests/test_dashboard
        }
    }
    "coverage" {
        Invoke-Step "Running the test suite with coverage" {
            & $python -m pytest -q --no-header --cov=fx_smc_bot --cov-report=term-missing
        }
    }
    "doctor" {
        Invoke-Step "Validating the checkout" {
            & $python -m fx_smc_bot doctor --config configs/base.yaml --strict
        }
    }
    "smoke" {
        Invoke-Step "Running the synthetic backtest" {
            & $python -m fx_smc_bot backtest --synthetic --bars 500 --log-level WARNING
        }
    }
    "dashboard" {
        Invoke-Step "Launching the dashboard" {
            & $python -m fx_smc_bot dashboard
        }
    }
}
