# Gate C6-R-CI-PDA Classifier Forensics

Generator: `scripts/run_gate_c6rci.py::build_prohibited_data_audit`.
The function derived `changed_paths` from `git diff --name-only origin/main...HEAD`, then treated any path containing a blocked token as prohibited.
It did not inspect extension semantics, size, schema, content role, or Git object type.
The token `holdout` caused policy documents, integrity metadata and access-control code to be treated as payload violations.
`build_quality_gate_final` did not consume this audit status, so the C6-R-CI decision did not expose the failure.
