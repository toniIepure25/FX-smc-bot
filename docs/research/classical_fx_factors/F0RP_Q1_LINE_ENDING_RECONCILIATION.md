# Gate F0-RP Q1 Line-Ending Reconciliation

Reconciliation ID:
`Q1_MANIFEST_LINE_ENDING_VALIDATOR_RECONCILIATION_V1`.

The canonical text helper hashes strict UTF-8 after replacing CRLF and bare CR
with LF. It is used only under
`SHA256_OF_UTF8_TEXT_WITH_LF_NORMALIZED_LINE_ENDINGS`. Explicit raw-byte mode
remains byte-sensitive, unsupported modes fail closed, and binary input is
rejected in text mode.

The Q1 manifest, lineage seal, closure lock, and all Q1 scientific artifacts
remain unchanged. The validator regression covers LF, CRLF, mixed line endings,
terminal and absent terminal newlines, binary rejection, and raw-byte
sensitivity.

The repository audit found that the sealed Q1 manifest itself has no
`hash_mode` field despite the prior Gate F0 diagnosis. Its records contain 12
LF-normalized digests, 25 raw CRLF digests, and four inherited Q0-R digest
values that match neither the current content nor any raw, LF, or CRLF Git
version of those paths. The validator now compares LF-normalized worktree
content with the LF-normalized tracked Git blob. It also verifies every
historical digest in its actual legacy representation and records the four
non-line-ending defects explicitly instead of silently accepting them.

This test-only correction does not alter a historical result or scientific
claim.
