"""FX_INTRADAY_ALPHA_DISCOVERY_V2 prospective, executable research protocol.

This package is the clean, self-contained V2 discovery stack. It deliberately does
not depend on the historical A0/A0R1/A0R2/A0R3 operational machinery beyond reusing
the *certified* execution and statistical kernels. Every admitted V2 strategy compiles
into a fully deterministic executable specification before any untouched 2018+ outcome
data is inspected.

Scientific invariants enforced across this package:

* The 2018+ holdout is never opened during readiness (see :mod:`firewall`).
* No strategy carries an unresolved semantic ``BLOCKED`` state into discovery; a
  strategy that cannot be fully specified is ``REJECTED_PRE_OUTCOME`` (see
  :mod:`compiler`).
* Tick-only quote semantics are never faked from M1 bars (see :mod:`capabilities`).
* All feature timing is causal (features at bar close ``t`` act at bar ``t+1`` open).
"""

from __future__ import annotations

PROGRAM_ID = "FX_INTRADAY_ALPHA_DISCOVERY_V2"
LINEAGE_ID = "FX_PRICE_MICROSTRUCTURE_ALPHA_LINEAGE_V1"
GATE_ID = "A0R4_V2_PROSPECTIVE_READINESS_V1"

__all__ = ["GATE_ID", "LINEAGE_ID", "PROGRAM_ID"]
