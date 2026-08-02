# Handover — records and workflow redesign

- **Date**: 2026-08-01
- **Task(s)**: none claimed; this session created work rather than draining it

The owner asked why `main` carried an eval record pointing at a `wip` branch,
then asked for the records workflow — and the instructions around it — to be
redesigned for how they actually work: batches of stacked PRs across several
areas, an all-in-one branch that verifies everything, and **answers to
`needs-human/` questions only after the whole batch has merged**.

## What happened

- **The records problem was not what it looked like.** It was described as
  commit pins broken by rebasing. Measured across the 42 real records in
  `evals/results/`: 3 contain nothing but a clean `main`-ancestor SHA, 31 are
  unparseable (prose, two SHAs, or a "+ uncommitted" qualifier), 6 have no
  `Git SHA` row at all, and **16 pin a commit plus a dirty working tree** — so
  the ancestry check passes while proving nothing about what was tested.
  Exactly 1 record still matches head. There was never a commit-pinning system
  to migrate; there was a free-text field. One record's "lost" SHA
  (`046a1f17e5f5`) turned out to be a four-character typo for `046a1f1780b5`,
  which is an ordinary ancestor of `main` and was never lost.
- **A live defect was found that blocks the owner's stated workflow.** A review
  ledger row's digest range started at *the most recent preceding ancestor row
  in the YAML list*, so a row's meaning depended on its position, not on the
  commit it named. Merging two branches cut from one base concatenates the
  rows, silently re-parents the second branch's first row, and the gate exits 2
  — on `main` itself, on the second parallel merge, green at pre-commit and red
  only once the merge commit exists. Reproduced twice independently in
  throwaway repos with the repo's own `review_gate.py`. Fixed in PR #183: a row
  may now carry its own `base:`, purely additively (all 161 legacy rows take
  the fallback and verify byte-for-byte unchanged).
- **Four designs were produced, adversarially reviewed, and cut down.** The
  reviewer found 15 false claims across them and rejected the AIO *branch*
  outright: it runs `--verify-all`, so it is red by construction. Nine PRs
  became the plan; three were dropped as over-built for this repo
  (`INDEX.md` under a hard gate, a 42-record backfill worth ~13 true pins, and
  `--verify-gate-claims`).
- **Six PRs are open** (#183–#188), each verified from its own worktree.

## Where things stand

All six are **open, green, and unmerged** — the session's merge attempt was
denied by a permission gate, so merging is the owner's call. Order matters:
merge #183 first, then retarget each child to `main` with
`gh pr edit <n> --base main` *after* its parent lands. Never `--squash`, never
`--rebase`, never "Update branch" (PR #184 fixes the three places the repo told
you to do exactly that; one of them closed PR #136 last batch).

- **#183** `fix/01-ledger-row-base` — the keystone. Blocks everything else.
- **#184** `docs/02-merge-recipes-and-count-rule` — the three wrong merge
  recipes; PR bodies may no longer state absolute tree-wide counts; PR template
  now passes its own checker. 4/4 canaries ran.
- **#185** `chore/03-ci-and-pr-body-gate` — CI measures the branch not the merge
  preview; `push` filtered to `main`; `types: [… edited …]` added; the eval
  gate is now mechanically enforced with a **debt** form.
- **#186** `feat/04-eval-record-pins` — content pins for **new** records only.
- **#187** `chore/06-housekeeping` — 31 tasks drained to `4_done`, 5 held; the
  `github-workflow` canary rubric corrected; the first record filed under the
  new schema.
- **#188** `docs/05-queue-merge-then-answer` — the queue protocol.

**Integration build** (a local instrument, never a branch: merge every terminal
tip into a scratch worktree, run the expensive suites once): all six merge, the
four parallel siblings conflict **only** on `review_ledger.yaml`, and after
row-granular concatenation the 175-row ledger verifies with **zero digest
mismatches**; reconciler 9 checks clean, leak guard clean, instruction budget
clean, all ten test suites green.

**Known and unfixed:** the review gate's one-commit lag is why 48 of 48 PRs
touch the ledger, which is why every parallel branch conflicts on it. PR #183
makes that conflict *safe to resolve*; it does not remove it. Fixing the lag
(acknowledge the staged tree, not HEAD) is smaller than anything shipped here
and is filed as a decision. Also: an older `review_gate.py` rejects a ledger
containing `base:` as an unknown key, so a stale worktree will error until it
is updated.

## Needs your attention

- **Merge the stack** — `gh pr merge 183 --merge`, then retarget children as
  above. Nothing else in this session can land until #183 does.
- [Delete the `wip/07-company-roles-jd-digest` branch?](../../../message-queue/needs-human/decisions/delete-the-company-roles-jd-digest-wip-branch.md)
  — it holds the only copy of one record's tested bytes and PR #182 pushed it
  yesterday to preserve them. Default: keep.
- [Does merge-then-answer apply to the private overlay?](../../../message-queue/needs-human/decisions/does-merge-then-answer-apply-to-the-private-overlay.md)
  — the overlay is a second repo with its own queue/tasks/evals/hooks and **no
  reconciler**, so nothing would enforce the new schema there. Default: public
  tree only.
- [Does the `Blocks:` rename supersede the stop-condition task?](../../../message-queue/needs-human/decisions/blocks-rename-supersedes-the-stop-condition-task.md)
  — that task recommends the opposite; the two must not ship independently.
  Default: rename ships, task marked superseded in place.
- [Should the review-gate design doc carry the `base:` key?](../../../message-queue/needs-human/decisions/should-the-review-gate-design-doc-carry-the-base-key.md)
  — `docs/designs/AGENTS.md` says historical families are records. Default:
  leave the design doc alone; the live description lives in the gate docstring.
- **Two things only you can do**, both outside the public tree:
  `verify_links.py` exits 1 in your primary checkout — 5 broken refs, all under
  `private/` (a retired `design/` prefix and two missing `private/data/email/…`
  paths); CI never mounts the overlay so nothing here is affected. And the
  overlay has ~78 uncommitted changes, including five application folders you
  moved between status folders — real pipeline work, uncommitted.
- **One judgement call worth ratifying or reversing**: #185 makes the `pr-body`
  CI job *blocking* for the eval-gate property. Any future PR touching
  `skills/*/{SKILL,LESSONS,reference}.md` now goes red until its body carries
  canary results, a written skip rationale, or a debt declaration with its
  backlog item in the same diff.
