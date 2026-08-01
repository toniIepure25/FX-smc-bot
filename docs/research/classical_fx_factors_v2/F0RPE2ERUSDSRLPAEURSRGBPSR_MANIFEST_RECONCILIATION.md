# Historical Manifest Reconciliation

Reconciliation ID: `HISTORICAL_MANIFEST_COMMIT_PINNING_RECONCILIATION_V1`.

Historical source manifest entries are verified against recorded Git blobs instead of the current working tree. The verifier uses the manifest's recorded implementation/source/certification commit for historical source files, normalizes line endings only under `SHA256_OF_UTF8_TEXT_WITH_LF_NORMALIZED_LINE_ENDINGS`, preserves raw-byte sensitivity under `SHA256_OF_RAW_BYTES`, and rejects repository path escapes.

The predecessor manifest was not edited. The previously failing LPA final-decision manifest test now passes because source hashes are reproduced from commit-pinned historical blobs, with a commit-pinned final-artifact fallback for source tests introduced in the same final manifest commit.
