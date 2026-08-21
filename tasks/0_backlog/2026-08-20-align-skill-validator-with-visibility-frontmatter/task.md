# Align skill validation with repository visibility metadata

- **Priority**: P2 (someday)
- **Area**: repo
- **Source**: 2026-08-20 subagent-count-limit removal session
- **Claimed-by**:

## Goal

Provide a skill-validation path that accepts this repository's required `visibility` frontmatter
without weakening the repository's own skill metadata checks.

## Context

The generic `skill-creator/scripts/quick_validate.py` rejects `visibility` as an unknown key. The
field is already present across this repository's public skills and was established by the
workspace visibility work; removing it from individual skills would violate the repository's
metadata model. The same incompatibility was previously observed in
`tasks/4_done/2026-07-23-email-notes-calendar-reconciliation/verification.md`, but no open item
tracks a durable validation path.

## Definition of done

- A documented repository command validates skill frontmatter while accepting the required
  `visibility` field.
- The command rejects genuinely unknown keys and passes the existing public skill tree.
