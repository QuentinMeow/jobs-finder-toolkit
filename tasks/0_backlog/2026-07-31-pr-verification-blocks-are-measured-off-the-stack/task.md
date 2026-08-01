# PR Verification blocks are measured off the stack, and nothing compares them to the tree

- **Priority**: P1 (this round)
- **Area**: harness
- **Source**: independent verification of the 25-PR stack #135–#157, 2026-07-31 (report
  written to this session's scratchpad, not tracked — every number it relies on is
  reproduced inline below so this task stands alone)
- **Claimed-by**: <(set when work starts, before the first change)>

## Goal

A pasted gate transcript in a PR body cannot silently describe a different tree from the
one being merged. The author gets a mechanical way to find out, at the moment they write
the body, that a number they pasted no longer matches the branch.

## Context

### The defect, and why it is one cause rather than twenty mistakes

Twenty agents each worked in an isolated `main`-based worktree (`local/wt/01…26`). Each
wrote its PR body's `## Verification` block **there**, then rebased the branch into its
stack position and never re-ran the block. The numbers were true where they were measured
and false where they were published. Three independent oracles show it, all measured at
each PR's own substantive commit in a pristine clone:

- **The reconciler check count is categorical.** PR #140 (`8a1321a`) added a ninth check,
  `public-registry-blacklist`. Ten PRs that sit **above** #140 in the stack publish
  `reconcile: OK (8 checks clean)`; their own commits give `9`: #141 `326e94f`, #142
  `0f7ce4d`, #143 `cb631f7`, #144 `35137fe`, #145 `708dc6c`, #146 `003916e`, #147
  `eca0c33`, #149 `9778181`, #152 `1e4b7c1`, #153 `eb9c32f`. A check that does not exist
  in the tree you ran against cannot be a snapshot taken slightly early.
- **Reference counts move backwards up an append-only stack.** `verify_links.py` rises
  monotonically `1698 → 2510` across the stack; the claimed sequence for #143 → #144 →
  #145 → #147 reads 1718, 1700, 1699, 1698 — decreasing. #156 claims 1862 where its own
  commit (`86a18e0`) gives **2508** (corrected 2026-07-31 — this line said 2505).
- **Suite sizes are reported as shrinking.** `automation/shared/tests` is accurate at and
  below #140 (#136 claims 455, actual 455; #139 claims 469, actual 469) and understated
  above it (#141 claims 459/actual 473; #147 claims 464/actual 482; #153 claims
  455/actual 489). Same shape in `skills/job-search/scripts/tests` (#153 claims 356,
  actual 406) and `automation/publish/tests` (157 claimed, 188 actual).

It is not confined to PR bodies. `tasks/3_in-review/2026-07-21-store-incremental-build-o-new/verification.md`
shipped the same five wrong numbers **into the repo** (its "whole store test surface"
block; corrected there 2026-07-31, with the wrong and right figures both kept). And
`tasks/0_backlog/2026-07-31-word-anchor-the-remaining-substring-keyword-lists/task.md`
asserted that `_title_prefilter` "still drops Software Engineer, Internal Developer
Platform" in commit `8699726`, whose own ancestor `6bec7a3` had already fixed it
(`git show 8699726:skills/job-search/scripts/sources.py` line 339 is already
`bounded_phrase_hit(...)`). Corrected there on 2026-07-31.

Aggravating: several bodies assert provenance rather than merely pasting a figure. #147
says *"Every command below was run on this branch"* above a block whose numbers are
`main`'s; #149 labels its block *"After the change, at branch head."*

### What a check would have to compare, and what it would cost

The four fast gates print one summary line each and are cheap. Re-measured on the stack
tip `40871e6`, 2026-07-31 (the table was first captured on `wip/28-verification-regressions`,
which reported 2537 references; the branch has moved since, which is the same staleness
this task is about):

| gate | summary line it prints | wall |
|---|---|---|
| `automation/reconcile/reconcile.py --check` | `reconcile: OK (9 checks clean)` | 0.28 s |
| `automation/gardener/verify_links.py` | `OK: 2552 references, the skill symlinks and the vendored copies verified.` | 3.22 s |
| `automation/metrics/instruction_budget.py --strict` | `OK: all instruction files within budget.` | 0.25 s |
| `automation/vendoring/sync_vendored.py --check` | `vendored copies in sync` | 0.19 s |

Total **≈ 3.9 s**. That is affordable anywhere.

**Test counts are the opposite.** They are the largest class of false claim in the stack,
and they are the expensive one: `automation/gardener/tests` alone is **165 tests in 83 s**
and `automation/publish/tests` is **188 in 131 s** on this machine; the whole 13-suite
battery is **1801 tests** over roughly eight minutes. (Corrected 2026-07-31 — the total read
1790, which is what the battery was one branch earlier.) A pre-push step that re-runs the
suites costs minutes per push, so it gets disabled — which is worse than not having it.

So the honest scope of the cheap version:

- **Catches** every reconciler-check-count claim, every `verify_links` reference count,
  the vendoring and instruction-budget one-liners. That is 10 of the 10 documented
  reconcile falsehoods and 8 of the 8 documented reference-count falsehoods.
- **Misses** every `Ran N tests` claim (the largest class), all timing claims (#150's gate
  cost, understated ~4×), diff-size claims (#140's eval-gate rationale, off ~6×), and
  every prose claim ("still dropped exactly as before" — the R3 recall regression). Those
  need a human or a different mechanism; the task must not pretend otherwise.
- A cheap partial extension worth costing: a *count-only* mode that collects
  `unittest --collect-only`-style totals without running the tests. Whether that is
  reliable per suite is an open question for whoever takes this.

### Where it lives — the PR body is not in the repo at push time

This is the hard part, and it rules out the obvious answer.

- **A pre-push hook cannot do the comparison.** On a first push the PR does not exist and
  the body has not been written; there is nothing to compare against. A pre-push step
  could at most *measure* and stash a block (say `local/gate-block-<sha>.txt`) for the
  author to paste — useful, but it verifies nothing on its own, and a stashed block is
  itself a transcript that can go stale.
- **`skills/github-workflow/scripts/check_pr_body.py` is the real home.** It already reads
  a body (from a file or stdin), it is already the documented pre-post step in
  `skills/github-workflow/SKILL.md` §1, it already exits 1 with per-line findings, and it
  already has a test suite. Proposed shape: `--verify-gate-claims`, which runs the four
  fast gates against the current checkout and, for each summary line it can parse out of
  the body, fails when the body's figure contradicts the freshly measured one. It runs at
  the moment the numbers are written, which is the moment they can still be fixed.
- **CI can be the backstop for free**, because `.github/workflows/ci.yml` already runs all
  four gates. A final step that fetches the body (`gh pr view --json body`) and diffs the
  same lines costs nothing extra, and it catches a body edited after the local check. It
  needs `pull_request` types `[opened, edited, synchronize]` or it will not re-run on an
  edit. Decide whether that is in scope or a follow-up.

### The failure mode to design against

A gate that blocks because a number legitimately moved will be bypassed, and this repo
forbids `--no-verify`. So the escape must not be "turn it off":

1. **Fail only on contradiction, never on absence.** A body with no gate lines passes. A
   doc-only PR is unaffected. The check has no opinion about what a body *should* contain.
2. **A labelled two-figure disclosure passes.** PR #152 already invented the right idiom —
   a "Merge note" that gives both the authoring-branch figure and the merged figure. If
   the body carries both and says which is which, the claim is true and the check must
   accept it. The escape is *disclose*, not *disable*.
3. **The local run is the fail-closed one; nothing blocks a push.** Pushing is not the
   moment the claim is published.

### The second-order point: this is a self-review failure too

All 25 new `automation/publish/review_ledger.yaml` rows read `reviewed_by: agent,
finding: none` — the same session that wrote each change certified it, and that produced
zero findings against roughly twenty false statements and four merge-blocking regressions.

**Do not weaken the ledger.** It is a leak gate, it caught a real company-name leak in an
earlier round, and its digest recomputation is what forces the diff into a reviewer's
context. Whether a row should additionally have to name the commit whose gate block was
re-measured is a genuine owner question, but bolting numeric honesty onto a privacy gate
blurs two different jobs and gives a reviewer two reasons to rubber-stamp instead of one.
Recommendation: keep them separate, and if the owner wants ledger-level enforcement, file
it as its own decision item rather than editing the ledger's contract inside this task.

## Definition of done

- [ ] `check_pr_body.py --verify-gate-claims` exists: runs the four fast gates against the
      current checkout, parses the same four summary shapes out of the body, and exits 1
      naming each contradicted line with both figures.
- [ ] Absence is never a finding; a body with no gate lines still exits 0.
- [ ] A labelled two-figure disclosure (the #152 "Merge note" idiom) exits 0, with a test
      that pins the accepted wording.
- [ ] Tests in `skills/github-workflow/scripts/tests/`, each proven to fail against the
      pre-fix checker, including one built from PR #153's real body text (claims 8 checks
      against a tree with 9).
- [ ] `skills/github-workflow/SKILL.md` §1 documents the flag next to the existing
      `check_pr_body.py` invocation; `CONTRIBUTING.md` unchanged unless the CI backstop
      lands with it.
- [ ] The scope limit is written down where an author will read it: test counts, timings
      and prose claims are NOT covered.
- [ ] Decided and recorded, either way: whether the CI backstop (`gh pr view` + `edited`
      trigger) is in this task or a follow-up.
