# Handover — wrap up the crashed session's stack

- **Date**: 2026-08-02
- **Task(s)**: none of its own — this session recovered and shipped the work of the
  2026-08-02 03:52–05:33 session, which a machine crash ended before it pushed anything.

## What happened

- **Nothing is on fire, and nothing was lost.** The crashed session's nine branches
  survived in the object store; only their worktrees were gone, because they lived under
  `/private/tmp`, which the reboot wiped. `git worktree prune` cleared the stale
  registrations. The private overlay repo was never in flight — it is clean and in sync
  with its origin, with nothing unpushed and nothing untracked.
- Nine rungs of defect fixes went from local-only to nine stacked PRs. The stack is a
  plain base-chain (**Track B**), each rung based on the one below, bottom rung on `main`.
- The whole stack was verified as one tree at the tip, which is the only tree these
  commits actually produce.

## Where things stand

- In review: nine PRs, bottom to top —
  `fix/vendor-reverse-audit`, `fix/leak-guard-fail-open`,
  `fix/never-delete-application-folder`, `fix/visa-classifier`,
  `docs/resume-writer-gate-truth`, `docs/job-search-location-routing`,
  `docs/owner-reporting-standard`, `fix/commands-that-fail-on-a-healthy-repo`,
  `chore/records-match-the-tree`.
- Merge them **bottom-up**, retargeting each child after its parent lands, or run
  `skills/github-workflow/scripts/merge_stack.py --execute` over the numbers. They are
  Track B, so nothing auto-retargets.
- `run_gates.py --group both` on the tip: 30 of 31 gates PASS. The one red gate is
  `tests-publish`, and it is red for a reason that has nothing to do with the stack — see
  *If X then Y*.

## Decisions made for you

- **PR #214 is closed as superseded, not merged.** It fixed one sponsorship-classifier
  shape; `fix/visa-classifier` fixes the same shape plus two more and closes the
  known-issue record that tracked all three. Both branches rewrite the same function, so
  merging both was never possible. Checked before closing, not assumed: the filed
  reproduction's third line — #214's entire subject — prints `unknown low review` on the
  stack, identical to the result #214 reports for itself. **Undoing it costs one
  `gh pr reopen 214`;** the branch is untouched on origin.
- **Branch names were left alone** even though the skill asks for a numeric segment so a
  stack's order is legible. `memory/known-issues/visa-sponsorship-negation-phrase-gap.md`
  names `fix/visa-classifier` as the branch that closed it, and renaming would have made a
  tracked record false to save a reader one glance. Each PR body states its rung instead.
- **The eval gate is discharged at the tip as tracked debt**, with
  `tasks/0_backlog/2026-08-02-run-canaries-for-the-nine-rung-defect-stack/`. A canary run
  is a live agent run against real boards and cannot be produced inside the PR that owes
  it. Rungs 5 and 6 defer to the tip by name; rung 5 also carries its own written skip
  rationale, which stands on its own.
- Verification was reported **at the tip, not per rung**. A per-rung number is stale the
  moment the rung above it merges, which this repo has already been bitten by.

## If X then Y

- **If `run_gates.py` shows `tests-publish` red, do not go looking for a leak-guard
  defect.** Two tests in it assume a real `private/` directory and generated runtime skill
  adapters, and a `git worktree` has neither. The same two fail **identically on `main` at
  `f360aec`** with the same setup, and both suites exit 0 with the overlay unmounted, which
  is CI's configuration — so CI is green. Filed as
  `tasks/0_backlog/2026-08-02-publish-suite-red-in-a-worktree-checkout/`.
- **If you work in a worktree, `git add -A` will stage a `private` symlink.** `.gitignore`'s
  `private/` entry has a trailing slash, so it matches a directory and not a symlink of the
  same name. Use explicit pathspecs. Same shape as
  `tasks/4_done/2026-08-01-gitignore-venv-does-not-cover-a-symlink`.
- **If the `example-render` gate leaves the tree dirty, that is expected.** It rewrites the
  example DOCX/PDF binaries with fresh timestamps and no content change. Restore them with
  `git checkout -- examples/applications/` before committing.

## Dead ends

- **Do not try to keep both #214 and `fix/visa-classifier`.** They are independent
  implementations of the same demotion — `_sponsor_negation_out_of_reach` against
  `_sponsor_cue_out_of_reach` — over the same lines of `job_metadata.py`, in four vendored
  copies each. Rebasing one onto the other is a hand-merge of two prose-heavy regex
  modules to reach a state one of them already occupies.
- `git checkout main` inside a worktree fails: `main` is checked out in the primary
  checkout and git refuses the second one. `git checkout --detach <sha>` is how to A/B
  against `main` from a worktree.

## Needs your attention

- [`job-search-us-only-default-asymmetry`](../../../message-queue/needs-human/decisions/job-search-us-only-default-asymmetry.md)
  — **Why this matters:** `us_only` defaults `False` when the search profile omits it and
  `True` when `config.yaml` omits it, so a profile with no `us_only` searches worldwide and
  then has its foreign picks rejected at handoff. It is the only pending item whose cost is
  `recurring-loss` — it quietly wastes search results on every run. **If you do nothing:**
  the default path is "change nothing", so the asymmetry stays and is now at least
  documented in both places.
- [`examples-reshape-seven-calls`](../../../message-queue/needs-human/decisions/examples-reshape-seven-calls.md)
  — **Why this matters:** the `examples/` reshape shipped to its own recommendations and is
  still awaiting ratification; still open from 2026-08-02's earlier session.
  **If you do nothing:** it stays as built, and declining later costs a revert rather than
  nothing.
- [`is-never-delete-owner-data-scoped-to-repo-local-products`](../../../message-queue/needs-human/decisions/is-never-delete-owner-data-scoped-to-repo-local-products.md)
  — **Why this matters:** decides whether the never-delete guardrail binds a live Outlook
  calendar event or only repo-local products. **If you do nothing:** the default is the
  intersection of both, so no agent behaviour changes.
- **`verify_links.py` is red with the overlay mounted** — 5 broken references, all inside
  `private/`, carried over from earlier renames. Pre-commit and CI pass `--no-overlay` so
  nothing is blocked; fixing it needs `private/` writes, so it stays owner-only. Filed as
  `tasks/0_backlog/2026-08-02-overlay-only-broken-links-are-invisible-to-both-gates`.
- 30 pending decisions overall, 25 of them `ratify` class.
