"""Allow ``python -m fx_smc_bot`` to behave like the installed ``fx-smc`` command."""

from fx_smc_bot.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
