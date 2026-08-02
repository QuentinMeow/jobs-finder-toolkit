# Handover — github merge pattern and folder refactor

- **Date**: 2026-08-02
- **Task(s)**: workspace phase 8 (`examples/` half); the merge-runbook correction;
  ten backlog defects; two repeated-mistake countermeasures.

## What happened

**The GitHub merge instructions in the skill did not work, and now they do.** This repo
uses GitHub's *native stacked pull requests* — a stack is a real server-side object with
its own number, and ten exist here. `gh` has no support for them, which is why
`gh pr merge` answers 403. That also settles a contradiction the skill had carried for
weeks: it said GitHub never auto-retargets a stacked child, while experience said it
does. **Both are true, of different objects** — inside a native stack GitHub retargets
and a member's base must not be hand-edited; outside one, nothing ever retargets. PR
#198 merged into an already-merged branch because it was in the second world while being
treated as the first. `skills/github-workflow/scripts/merge_stack.py` now classifies
before merging and refuses rather than advising, and `AGENTS.md` routes every GitHub
operation through the skill.

**The `examples/` reshape is built.** Its decision item's own pre-registered fallback
fired when the owner said "continue the folder refactor". `examples/data` → `store`,
`profile` → `me`, `templates/` deleted, `0_profile` dissolved. The questions are
unchanged and unanswered; declining now costs a revert rather than nothing.

**Ten backlog defects fixed**, the most serious being a store data-loss path: a dangling
symlink `manifest.json` read as *absent*, so the GC deleted the blob it referenced and
retention deleted the live fetch directory. Fixed at three sites, not the one filed —
glob's treatment of dangling symlinks is Python-version-dependent, and CI pins 3.12
while the floor is 3.11, so a classifier-only fix would have gone green in CI with the
floor still broken.

**Two repeated mistakes got mechanisms instead of prose.** The piped-exit-code defect was
closed with a written convention on 2026-07-31 and repeated on 2026-08-01;
`automation/gates/run_gates.py` now runs all 31 gates with redirected output and an
exit-code table, so the unsafe shortcut has no motive. The lesson is in
`memory/lessons/harness/broken-twice-build-the-check.md`.

## Where things stand

Eleven stacked PRs, **#203 → #213**, each based on the one below. All Track B (a plain
base-chain, **not** a native stack), so nothing auto-retargets: merge bottom-up and
retarget each child after its parent lands, or run
`merge_stack.py --execute 203 204 … 213`, which does both and verifies each step.

All 31 gates green on the tip (29 PASS, 2 structural SKIP), `--verify-all` 0 across 225
ledger rows.

Two defects were caught *by* this session's own new checks: the gate-table drift test
caught a table pinning `examples/data` after a sibling branch renamed it — a semantic
contradiction git could not see because nothing conflicted; and the pre-commit link
check caught a lesson referencing a file on another branch.

## Needs your attention

- **[`examples-reshape-seven-calls`](../../../message-queue/needs-human/decisions/examples-reshape-seven-calls.md)**
  — the reshape is built to its recommendations; ratify or revert. D5 needs only
  ratification (it shipped in `ac34371`). Three destinations were derived from the
  private mirror and are named in the item.
- **[`is-never-delete-owner-data-scoped-to-repo-local-products`](../../../message-queue/needs-human/decisions/is-never-delete-owner-data-scoped-to-repo-local-products.md)**
  — does that guardrail bind a live Outlook calendar event, or only repo-local products?
  Default while pending: the intersection of both, so nothing an agent does changes.
- **`verify_links.py` is red with the overlay mounted** — 5 broken refs, all inside
  `private/`, from the phase-2 and phase-5 renames. Pre-commit and CI are unaffected
  (they run `--no-overlay`), so nothing is blocked, but the gardener routine has been
  failing. Fixing it needs `private/` writes, so it is owner-only.
- 27 further pending decisions, all `ratify` class. Top by cost:
  `2026-07-31-re-enrich-yoe-after-attribution-fix` (`one-time`).
