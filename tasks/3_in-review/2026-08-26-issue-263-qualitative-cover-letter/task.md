# Give sparse sources a truthful cover-letter evidence path

- **Priority**: P1 (this round)
- **Area**: resume-writer
- **Source**: GitHub issue #263; orchestrated issue-resolution session 2026-08-26
- **Claimed-by**: Codex GPT-5.6 Sol xhigh

## Goal

When the candidate's approved sources contain no relevant metric, let the cover-letter recipe use
a concrete, verifiable qualitative example without weakening traceability or inviting an invented
number. Preserve quantified evidence as the preferred path whenever a relevant source-backed metric
does exist.

## Context

The current cover-letter instructions require paragraph two to use a real quantified achievement,
while the repository's hard no-fabrication guardrail forbids inventing metrics. A truthful sparse
profile can therefore satisfy the validator with a concrete qualitative example but cannot satisfy
the written workflow. The change must define a narrow precedence rule, add a sparse-source canary,
retain the existing quantified-source behavior, and avoid any parser or validator relaxation.

## Definition of done

- `skills/resume-writer/SKILL.md` and `reference.md` prefer a relevant source-backed metric when one
  exists and authorize a concrete, source-backed qualitative example only when none exists.
- The instructions explicitly forbid estimating, calculating, rounding, or inventing a number to
  satisfy the cover-letter recipe.
- The resume-writer canary set covers both sparse qualitative evidence and the existing quantified
  path, and passes on GPT-5.6 Sol xhigh.
- Impacted tests, repository gates, the review ledger, verification record, worklog, and session
  handover are complete.
