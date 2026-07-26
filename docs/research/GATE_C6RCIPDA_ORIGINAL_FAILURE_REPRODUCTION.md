# Gate C6-R-CI-PDA Original Failure Reproduction

Original C6-R-CI `prohibited_data_audit.json` status: `FAIL`.
The legacy classifier was reproduced with `blocked_patterns = [data/raw/, data/canonical/, .parquet, .bi5, holdout]`.
Reproduced status: `FAIL`.
Reproduced prohibited path count: `21`.
The reproduced path set matches the committed failing artifact.
