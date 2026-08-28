# Design — truthful cover-letter evidence precedence

## Decision

Cover-letter paragraph two uses the strongest relevant evidence that the approved candidate sources
actually contain:

1. When a relevant source-backed metric exists, use that real quantified achievement.
2. When no relevant source-backed metric exists, use a concrete, verifiable qualitative example:
   a specific action, duty, artifact, or process, plus an outcome only when the approved sources
   support it.
3. Never estimate, calculate, round, or invent a number to satisfy the recipe. Preserve an
   estimated or unverified source figure's original framing rather than promoting it to fact.

The fallback changes the evidence form, not the repository's traceability or no-fabrication rules.

## Why this boundary

The prior quantified-only wording made an honest sparse profile impossible to use even though the
renderer accepts truthful qualitative prose. Making metrics merely optional everywhere would also
be wrong: it could erase stronger evidence already present in a rich source. The precedence rule
keeps the quantified path when supported and opens only the otherwise-unsatisfiable sparse path.

No validator or parser changes are needed. Relaxing them would broaden the patch without protecting
against the actual failure, which is an instruction conflict.

## Attack and consequences

- A vague fallback could turn into generic self-praise, so the rule requires a specific,
  source-backed action or artifact and allows an outcome only when it is also supported.
- A model could derive a plausible metric from duties, so the rule names estimating, calculating,
  rounding, and inventing as forbidden behaviors.
- A fallback could accidentally displace a real metric, so the existing quantified fixture now
  explicitly requires the source-backed metric while a separate sparse fixture contains none.
- Doing nothing preserves a contract that cannot be followed truthfully for sparse candidates;
  broadening the fallback without traceability would instead increase fabrication risk.

## Acceptance and rollback

Accept only if the full resume-writer canary set passes, including both the quantified-source and
sparse-source paths, and the deterministic resume-writer tests and repository gates remain green.
Roll back if the sparse canary produces a number or unsupported outcome, if the quantified fixture
stops using its real relevant metric, or if the instructions permit generic praise to substitute
for source-backed evidence.
