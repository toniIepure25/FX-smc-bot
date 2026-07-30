# P0 Execution Specification

Signals may be acted upon only after the signal bar is final.
Primary fills use executable bid/ask semantics and adverse-first same-bar ambiguity.
Missing or uncertified data produces `NO_TRADE_WITH_RECORDED_REASON`.
