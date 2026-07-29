# Gate C6-R-CI-PDA Root Cause

Root cause: `PATH_TOKEN_FALSE_POSITIVE` in `scripts/run_gate_c6rci.py::build_prohibited_data_audit`.
Secondary integration defect: `STATUS_DERIVATION_DEFECT`, because C6-R-CI quality output did not include the prohibited-data audit status.
The fix must classify by content role and fail closed on ambiguity without weakening payload detection.
