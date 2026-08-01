# ECB Identities

Metadata-only ECB checks returned 200 for EON, EST, ECB_EON1 and ECB_EST1. The preserved correction is source identity, not a relaxation of response validation.

- EON dataflow: `EON`; DSD: `ECB_EON1`; meaning: Internal Eonia Rate.
- EST dataflow: `EST`; DSD: `ECB_EST1`; meaning: Euro Short-Term Rate.
- Metadata responses are not numerical observation payloads.
