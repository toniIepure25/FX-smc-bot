# Gate C5-A-R-IR Lock Generation Audit

Expected hash origin: raw_crlf_sha256_of_4cd388b_validation_criterion_adjudication.

Exact defect: post_validation_lock stored the CRLF raw SHA-256 of the 4cd388b adjudication artifact and was not regenerated after abd879c changed only the non-scientific source_hash reference for the artifact_integrity criterion.
