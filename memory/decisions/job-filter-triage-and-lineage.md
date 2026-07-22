# Preserve ambiguous job roles and source metadata for review

- **Status**: decided
- **Date**: 2026-07-22
- **Decided by**: agent (within standing policy)
- **Supersedes / Superseded-by**: none

## Context

The job-search pipeline hard-rejected every title outside a configured include
list before reading job-description semantics. That made unconventional
software-engineering titles invisible and made the existing variant audit
incapable of evaluating those false negatives. Separately, explicit level
phrases and source-native compensation could be present upstream but absent
from generated metadata, while unfilled ATS templates could look like matches.

## Decision

Keep explicit profile excludes and definite non-technical occupations as hard
title rejects. Route the residual occupation-ambiguous family to a bounded
review report after all other gates, enrichment, dedupe, and scoring. Audit
hard rejects through a first-reject census with deterministic bounded samples.

Use explicit JD-body level phrases as low-confidence level evidence and flag a
material title/JD level conflict for review; level evidence never changes
occupation. Parse source-native structured salary only when currency and period
are explicit, preserving JD-text precedence, and carry the same fact through
raw rebuilds. Hard-reject unmistakable title or dummy-text templates; weaker
placeholder and repeated-boilerplate signals go to review.

## Alternatives considered

- Add aliases for individual unconventional titles — rejected as brittle and
  unable to cover new title families.
- Accept every unknown title as a match — rejected because it would mix
  non-engineering occupations into the shortlist.
- Keep hard rejects but sample only accepted rows — rejected because that
  cannot measure false-negative recall.
- Infer missing compensation currency or period — rejected because it would
  fabricate a fact.

## Consequences

The primary shortlist stays precise while plausible unconventional roles remain
inspectable. Review volume is bounded only after relevance gates, so irrelevant
source order cannot consume the cap. Filter audits now expose rejection
families rather than reporting a misleading clean result. New title, quality,
or location shapes require a fictional minimal corpus case after private
verification. Revisit the occupation lexicon or cap when real-data audits show
material false-positive or false-negative families.
