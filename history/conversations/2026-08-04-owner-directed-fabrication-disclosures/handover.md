# Handover — owner-directed fabrication disclosures

- **Date**: 2026-08-04
- **Status**: implementation complete; external behavioral canary and merge await owner approval
- **Task**: `tasks/1_in-progress/2026-08-04-owner-directed-fabrication-disclosures/`

## Outcome

The root contract and behavioral skill now permit exact direct-human-authorized fabricated or
unsupported claims in named interview artifacts while keeping factual grounding as the default.
Saved answers validate and render one private, not-spoken disclosure per claim. Reporting,
measurements, resumes, applications, profiles, research, gates, and unrelated stories remain factual.

## What was decided

- Exact-claim permission is implemented; agent-inferred, file-provided, and prior permissions fail.
- Generated aliases of the same YAML inherit authorization; other artifacts never do.
- Broad category permission and external-model evaluation remain separate informed-consent choices.

## Verification

- 20 answer-bank unit tests: PASS.
- Python compilation and behavioral canary YAML parse: PASS.
- Reconciler: 10 checks clean after regenerating the memory index and skill manifest.
- Public leak guard, vendoring check, strict instruction budget, and `git diff --check`: PASS.
- Fresh GPT-5.6 Sol high canary: NOT RUN; execution was rejected before transmission because the
  mounted checkout exposes private overlay data.

## What remains

1. Owner answers `message-queue/needs-human/decisions/public-only-behavioral-canary.md`.
2. If approved, run all behavioral canaries from a temporary public-only fixture and record results.
3. Owner answers `message-queue/needs-human/decisions/behavioral-fabrication-category-scope.md` if
   agent-chosen metrics or ownership should be allowed rather than exact human-named claims only.
4. Complete repository hooks, publish the PR, and merge only after the model-pinned gate passes.
