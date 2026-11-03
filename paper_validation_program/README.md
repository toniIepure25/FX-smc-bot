# Paper Validation Program (legacy)

This directory contains the design of a 4–6 week paper-trading validation
programme for the earlier `bos_only_usdjpy` candidate (created 2026-04-12).

**Status: not executed.** No session directory or recorded run exists here, and
the candidate predates the 2026 V1–V5R alpha-discovery programme, which closed
with no survivor. Treat these documents as historical design material, not as
evidence of an edge or as an approved plan.

If the programme is ever revived:

1. read [../docs/STATUS.md](../docs/STATUS.md) first;
2. record an explicit decision and a new date;
3. re-validate the candidate and its config on current, permitted data;
4. keep the hard-stop and invalidation rules;
5. store sessions under `sessions/` (ignored by git) and publish only reviewed
   summaries.

Key documents:

- [paper_validation_program.md](paper_validation_program.md) — programme design;
- [paper_program_manifest.json](paper_program_manifest.json) — candidate, risk
  profile and promotion criteria;
- [paper_stage_checkpoints.md](paper_stage_checkpoints.md) — review schedule;
- [paper_stage_invalidation_rules.md](paper_stage_invalidation_rules.md) —
  hard stops;
- [week_6_final_paper_review.md](week_6_final_paper_review.md) — final decision
  template.
