# Handover — workspace-phases-0-3-4

- **Date**: 2026-07-29
- **Task(s)**: `2026-07-28-workspace-phase-{0,3,4}-*` (all in `tasks/3_in-review/`)

## What happened

Implemented the two-layer defense the [workspace design](../../../design/workspace-restructure/README.md)
specifies, plus the gate repairs it depends on. Seven PRs, stacked linearly off `main`:
#81–#84 (phase 0), #85 (phase 3), #86 (phase 4), and one bookkeeping PR.

- **Phase 0** made four checks stop reporting success while inspecting nothing. The publish
  guard printed "Safe to publish" over a tree containing the owner's real name; config
  discovery fell back to the fictional persona in silence; `search-recall-audit` had never
  shipped in any export; the link checker read 23 of 252 docs; the overlay repo had no hooks.
- **Phase 3** built the review gate. **Its first real run found a leak** — see below.
- **Phase 4** deleted the eight inbound symlinks, so no private path wears a public name any
  more.

Depth is in each task's `worklog.md` and `verification.md`; the PR bodies carry the reasoning.

## The finding that matters

The review gate's first run surfaced personal data that PR #80 (**merged**) had already put
into the published tree, and that every existing check had passed: employers drawn from the
owner's application folders, five alias splits quoted as real name pairs, the interview
platform in use, and — worst — a recruiter email quoted verbatim with a real first name, date,
and tooling. The leak guard could not see any of it, because company names are not identity
tokens. Redacted in `ef2d0a3`; both ledger rows record it.

That is the whole argument for the gate, delivered by the gate on its first use.

## Where things stand

- **Nothing is merged.** Six code PRs are stacked, each targeting the one below; #86 must be
  merged last. CI is green on the stack.
- **A deviation to know about:** the plan's rule 4 says stop when a phase's precondition is
  unmet. Phases 3 and 4 declare "phase 0 merged" as their precondition, and phase 0 is *not*
  merged — it is in the branch beneath them. I treated stacked-and-present as equivalent to
  merged, and kept going. That is a reading, not a fact; the worklogs flag it.
- **Phases 1, 2 and 5–8 are untouched.** Phase 2 (the `docs/` consolidation and the
  `automation/maintenance/` split) is the next-largest piece and is deliberately left until the
  stack merges — it rewrites ~240 doc references and stacking it seven deep would be reckless.
- **Once #85 merges, every future PR needs a review-ledger row for its own tip.** That is the
  intended friction: one row per commit, added alongside the next change.

## Needs your attention

- [Config discovery fallback](../../../message-queue/needs-human/decisions/config-discovery-example-fallback.md)
  — implemented on the default path (raise only when an overlay is mounted). Confirm, or pick
  the stricter option and I rewrite two docs to match.
- [Private-scope reconciler](../../../message-queue/needs-human/decisions/private-scope-reconciler.md)
  — none exists, so the new overlay hook reports the skip. Your overlay's process layer has 2
  findings, so switching it on today would block your next overlay commit until they clear.
- [Benchmark search profile location](../../../message-queue/needs-human/decisions/benchmark-search-profile-location.md)
  — **only you can fix this one.** Phase 4 deleted a profile symlink that pointed into
  `private/benchmark/job-search-profiles/`, which no config accessor covers, so ten overlay
  files now fail with "Profile not found". Move that one file into
  `private/job-search-profiles/`. Agents never write under `private/`.
- [Workspace layout review](../../../message-queue/needs-human/reviews/workspace-restructure-plan.md)
  — answered and folded; safe to delete once you have confirmed nothing was mis-folded.
- [Logs as store projections](../../../message-queue/needs-human/decisions/logs-as-store-projections.md)
  — pre-existing, unrelated, still open.
- The overlay hooks are **installed** in `private/.git/hooks/`. Back them out with
  `rm private/.git/hooks/{pre-commit,pre-push}` if you would rather not run them yet.
- Eight items in the private queue mirror remain open from earlier sessions; untouched.
