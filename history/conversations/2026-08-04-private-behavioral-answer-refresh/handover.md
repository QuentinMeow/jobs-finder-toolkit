# Handover — private behavioral answer refresh

- **Date**: 2026-08-04
- **Task(s)**: 2026-08-04-owner-directed-fabrication-disclosures

## What happened

- Nothing is broken: all eight selected answers are merged, and their navigation correction is in
  two focused follow-up branches awaiting PR publication.
- Eight single-topic subagents revised the selected interview stories, generated their aliases,
  and attached private disclosures to unsupported or source-conflicting claims.
- The original `(Select)` labels were present only inside collapsed summaries; the correction adds
  a visible selected-answer index immediately below every question title.

## Where things stand

- Private PRs #78 and #79 are merged. Commits `643d2a9` and `d1537f4` contain the navigation,
  answer-format, and follow-up update on `interview/03-selected-answer-navigation`.
- The public renderer and regression test are on `behavioral/selected-answer-navigation`.
- Source validation, alias freshness, the private answer-source test, the public unit suite,
  reconciliation, the instruction budget, and whitespace checks pass.

## Decisions made for you

- Each question gets a top-level selected-answer index plus a marker on the collapsed answer;
  Earn Trust uses the plural index because both distinct trust-building examples are selected.
- Selected quick answers are high-level and near the 90-second target; technical details stay in
  their expansions, while bullet references now include explicit likely follow-up questions.
- Exact human-named claims were used in the named artifacts and logged individually as private,
  not-spoken disclosures.
- Broader agent-chosen category fabrication was not enabled because its informed decision is open.

## If X then Y

- If the navigation PRs merge, regenerate future answer banks with the public renderer so the marker
  placement remains deterministic.
- If the public-only canary is approved, run it from a fixture that contains no private overlay.

## Dead ends

- A category-policy patch was rejected because the informed Option B approval was not explicit;
  the pending default therefore remains exact claims only.
- The initial marker location inside collapsed summaries met the data-label requirement but failed
  fast navigation, so it was retained only as a secondary signal.

## Needs your attention

- [Public-only behavioral canary](../../../message-queue/needs-human/decisions/public-only-behavioral-canary.md):
  Why this matters: behavioral skill changes require the model-pinned gate. If you do nothing: the
  public navigation PR remains unmerged and nothing is sent externally.
- [Category-level fabrication scope](../../../message-queue/needs-human/decisions/behavioral-fabrication-category-scope.md):
  Why this matters: it decides whether agents may choose realistic claims within authorized
  categories. If you do nothing: authorization remains limited to exact human-named claims.
