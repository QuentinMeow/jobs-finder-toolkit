# PR Verification blocks are measured off the stack, and nothing compares them to the tree

- **Priority**: P0 (raised from P1 on 2026-08-01 — the defect recurred twice more after this
  task was filed, once inside the pass written to fix it, and twice again after the pass that
  wrote the rule against it; see "Round three")
- **Area**: harness
- **Source**: independent verification of the 25-PR stack #135–#157, 2026-07-31 (report
  written to this session's scratchpad, not tracked — every number it relies on is
  reproduced inline below so this task stands alone). **Extended 2026-08-01** by a second
  verification of #160–#172 — see "Round two" below, which is why the scope of this task
  changed — and again the same day by a fourth pass over #173–#175, which is "Round three"
  and is the evidence that the instruction-shaped fix is finished failing.
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

It is not confined to PR bodies. `tasks/4_done/2026-07-21-store-incremental-build-o-new/verification.md`
shipped the same five wrong numbers **into the repo** (its "whole store test surface"
block; corrected there 2026-07-31, with the wrong and right figures both kept). And
`tasks/4_done/2026-07-31-word-anchor-the-remaining-substring-keyword-lists/task.md`
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
- **Misses** all timing claims (#150's gate cost, understated ~4×), diff-size claims
  (#140's eval-gate rationale, off ~6×), and every prose claim ("still dropped exactly as
  before" — the R3 recall regression). Those need a human or a different mechanism; the
  task must not pretend otherwise.
- **Suite counts are now IN scope** — see "Round two", which is what changed this. The
  *count-only* mode this task previously left as an open question was measured on
  2026-08-01 at `a0365ec` and it is both cheap and exact:

  ```python
  unittest.TestLoader().discover(s, top_level_dir=s).countTestCases()
  ```

  | suite | collect-only | actually `Ran` | wall |
  |---|---|---|---|
  | `automation/shared/tests` | 593 | 593 | 0.55 s |
  | `skills/job-search/scripts/tests` | 503 | 503 | 0.47 s |
  | `automation/gardener/tests` | 165 | 165 | 0.23 s |
  | `automation/publish/tests` | 188 | 188 | 0.23 s |

  Four suites in **1.5 s** against roughly eight minutes to run them, and the collected
  total equals the run total in every case. The "it costs minutes so it gets disabled"
  objection above applies to *running* the suites, not to counting them. There is no
  remaining reason to leave the largest class of false claim uncovered.

### Round two — what this task, as originally scoped, would NOT have caught

A second verification (#160–#172, 2026-08-01) found nine of thirteen bodies publishing a
false `verify_links` count. Re-measured at each PR's own substantive commit in a
config-less clone with no overlay:

| PR | commit | claimed | actual |
|---|---|---|---|
| #160 | `8fb6f91` | 2537 | **2547** |
| #162 | `9d31abe` | 2554 | **2552** |
| #163 | `6a1c857` | 2552 | **2566** |
| #164 | `71de852` | 2566 | **2580** |
| #165 | `bfd3e11` | 2571 | **2599** |
| #166 | `95c52a5` | 2600 | **2598** |
| #168 | `cf511b4` | 2598 | **2639** |
| #169 | `8c2b93e` | 2600 | **2650** |
| #172 | `d1fdba6` | 2658 | **2656** |

The `--verify-gate-claims` shape proposed above **would have caught all nine**, and #161's
`reconcile: OK (8 checks clean)` (actual 9) as well. It would have missed four things, and
each is a real gap in the original scope:

1. **Stale suite counts.** #169 and #170 both publish `automation/shared/tests` = 587 where
   their own commits give **593**; #170 also publishes `skills/job-search/scripts/tests` =
   488 (actual **493**) and "was 477" (actual **482**); #160 publishes 468 (actual **473**).
   Explicitly out of scope before. Now in scope, via the measured count-only mode above.
2. **Numbers in prose, not in a fenced gate transcript.** #164 states "this PR itself adds
   14 references to the tree" in body prose, and #167 states "2598 at the branch point" in
   a sentence. A parser that only reads fenced blocks sees neither. The check must scan the
   whole body.
3. **Two runs spliced into one line.** #164 published
   `0 broken of 2566 verified · … · 1201 refs NOT verified`. `2566` is `c819f0d`'s and
   `1201` is `40871e6`'s, so the line **matches no commit in the history** — every field
   individually plausible, the pair impossible. A checker comparing only the headline count
   would pass the `2566` half against the wrong base and never look at `1201`. Compare
   every field on the line, together.
4. **Tracked records are not PR bodies.** The corrections pass wrote a reference count no
   commit reports into
   `tasks/4_done/2026-07-31-gate-documented-commands/verification.md`. `check_pr_body.py`
   is never pointed at a tracked `verification.md`, so nothing in the original scope could
   have seen it — even though the Context above already noted the defect "is not confined to
   PR bodies". That gap is now a DoD item.

**And one check that needs no oracle at all: compare against the parent.** It catches a large
share of the class without knowing the true value, works on any body, and is the cheapest
item on this list — it is what found #170, which the verification report missed entirely.
Measured parent → own-commit for all thirteen:

- **Three publish a count below their own parent's**: #165 (2571 vs parent 2580), #168 (2598
  vs 2620), #169 (2600 vs 2639).
- **Two publish a count exactly equal to their parent's**: #163 (2552, parent `40871e6` =
  2552) and #164 (2566, parent `c819f0d` = 2566) — the signature of pasting the base's value.
  Worth flagging separately, because a PR that touches any tracked `.md` almost always moves
  the reference count.

**Do not state this as "counts only rise" — that is false in this very range.** #166
(`95c52a5`) legitimately takes the count *down*, 2599 → **2598**, because rewriting the
handover removed a reference. So a below-parent count is a **flag demanding a re-measure**,
not proof of error; the checker must report it as "below parent, confirm this is a deletion"
rather than as a hard failure, or the first legitimate doc-deleting PR teaches everyone to
ignore it.

(For the record, the source verification report got this sub-claim wrong in both directions:
it named four below-parent PRs, #163, #164, #165 and #168, but #163 and #164 are *equal* to
their parents rather than below, and #169 — which is below — was left out.)

### Round three — the rule was written, and did not survive two commits

On 2026-08-01 the third correction pass (#173) wrote the rule *"Every number in a body belongs
to one commit — name it"* into `skills/github-workflow/SKILL.md` §1. The class recurred in the
two commits stacked directly on top of it, and in #173's own body. Re-measured 2026-08-01
across **all 93 commits** in `main..bbaf13bd` (the 41 PR tips, their substantive commits, the
ten intermediate rebase commits, and the merge-base), `verify_links --require-roots
--no-overlay` in a config-less worktree with no overlay:

| PR | own commit | published | measured | |
|---|---|---|---|---|
| #174 | `5f1ebc98` | `2658 … 1244` | **2668 … 1247** | matches no commit; `1244` is #171/#172's |
| #175 | `10479ae8` | `2670` | **2668** | matches no commit; commit **was** correctly named |

**The decisive datum is #175.** It obeyed the rule's most-cited bullet — it named the commit
its figure belongs to — and published a false figure anyway. Naming the SHA made the claim
checkable; it did not make it true. An instruction can specify the *shape* of a claim. Nothing
in a body's shape distinguishes a measured number from an unmeasured one.

**The parent comparison is anti-correlated on this round, on the one case it was needed for.**
The rule offers it as "a free self-check that needs no oracle", and flags a count *equal* to
the parent's as "the signature of pasting the base's value". At #175 the **true** count (2668)
is exactly equal to its parent `70e7192e`'s, so the rule would have flagged the correct answer;
the **false** count (2670) sits +2 above the parent and passes the heuristic cleanly. It does
fire correctly on #174 (2658 is below its parent `b1f01a75`'s 2664). So the check is worth
running and worth keeping — but it must be reported as a prompt to re-measure, never as
evidence either way, and the checker must not treat "above parent" as a pass.

**Two claim classes this round adds, both currently listed as out of scope, both mechanically
checkable.** They are not timings and not prose behavioural claims — they come straight out of
`git`:

1. **Diff-size claims.** #173's eval-gate rationale states its `SKILL.md` edit "gained 37 lines
   (32 non-blank instruction lines)". Measured at `a0365ec..f22b0067`: `--numstat` gives
   **42 added / 1 removed**, `wc -l` goes 340 → 381 (**+41 net**), and **37** of the added
   lines are non-blank. `32` corresponds to no natural measure of the edit; the only
   construction that yields it is non-blank added lines *excluding those that open a bullet* —
   which drops the five lines carrying the rule itself. This figure decides whether the eval
   gate MUST run (the trigger is ~20 changed instruction lines), so it is a gate input, not
   decoration. `git diff --numstat <base>..<head> -- <path>` answers it exactly.
2. **Staged/changed file counts.** #173's checklist says "(4 staged files, 0 non-markdown)"
   while its own Verification block says "5 files, all markdown" three paragraphs earlier.
   `git diff --name-only a0365ec f22b0067` gives **5**. One body, two numbers, no run.

**An implementation trap for the count-only suite mode, measured 2026-08-01 at `5f1ebc98`.**
`TestLoader().discover(s, top_level_dir=s).countTestCases()` must run **one process per
suite**. Counting all thirteen suites in a single process reports
`skills/email-assistant/scripts/tests` as **15** where the suite actually runs **79** — test
modules of the same basename in earlier-discovered suites are already in `sys.modules`, so
discovery silently drops them. In separate processes it reports 79, matching the run. A
checker that batches for speed would publish a false number of its own, which is the entire
defect this task exists to stop.

**Conclusion: instruction is exhausted; stop trying to word it.** Three passes have now
written prose against this class — #164's "Repeating the defect being fixed would be a poor
joke", #173's §1 rule, and #175's own hedge — and the class recurred immediately after each,
including inside the pass that wrote the rule and inside the hedge written to prevent a fifth
recurrence. Nothing in this task should be closed by adding a fourth exhortation to
`SKILL.md`, `CONTRIBUTING.md`, or a template. The remaining fix is the mechanical one below.

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
- [ ] **Suite counts are covered**, via `TestLoader().discover(...).countTestCases()` rather
      than by running the suites (measured 2026-08-01: four suites in 1.5 s, collected total
      equal to the run total in all four). A `Ran N tests` claim that contradicts the
      collected count for that suite path is a finding. **One subprocess per suite** — see
      Round three: batching all thirteen into one process reports `email-assistant` as 15
      against a real 79. Pinned by a test that counts two suites sharing a module basename.
- [ ] **The whole body is scanned, not only fenced code blocks.** A count asserted in prose
      ("this PR itself adds 14 references to the tree") is checked exactly like one inside a
      transcript. Pinned by a test built from #164's real prose line.
- [ ] **Every field on a gate line is compared together, not just the headline number.** A
      body pairing one commit's `verified` count with another commit's `refs NOT verified`
      is a finding even when each field alone is plausible. Pinned by a test built from
      #164's real published line (`2566` + `1201`, a pair no commit produces).
- [ ] **A parent comparison runs with no oracle**: for each parseable count, compare against
      the same count on the merge-base of the branch, and flag any claimed value *below* the
      parent's as worth a re-measure on an additive stack. This must work when the gate cannot
      be run at all, and it must name the parent SHA in the finding. **It is a prompt, never a
      verdict, and "above parent" is never a pass** — Round three measured it firing on the
      correct answer (#175's true 2668 equals its parent's) while the fabricated 2670 sailed
      through. Pinned by a test built from #175's real pair.
- [ ] **Diff-size and changed-file-count claims are covered**, from `git diff --numstat` and
      `--name-only` against the branch's merge-base. Round three: #173's eval-gate rationale
      claims "gained 37 lines (32 non-blank)" for a `+42/−1`, net `+41` edit whose non-blank
      added count is 37, and its checklist says "4 staged files" where its own Verification
      block and `git` both say 5. The diff size decides whether the eval gate MUST run, so it
      is a gate input. Pinned by tests built from both real lines.
- [ ] **Tracked records are covered too.** A `verification.md` under `tasks/` carrying a gate
      count is checkable by the same code path — either `check_pr_body.py <path>` accepts it
      or the reconciler grows the check. Decide which, and record the choice in the task's
      `worklog.md`. Pinned by a test built from the real 2026-08-01 defect: a `2566` in
      `tasks/3_in-review/2026-07-31-gate-documented-commands/verification.md` that no commit
      in the history reports.
- [ ] Absence is never a finding; a body with no gate lines still exits 0.
- [ ] A labelled two-figure disclosure (the #152 "Merge note" idiom) exits 0, with a test
      that pins the accepted wording.
- [ ] Tests in `skills/github-workflow/scripts/tests/`, each proven to fail against the
      pre-fix checker, including one built from PR #153's real body text (claims 8 checks
      against a tree with 9).
- [ ] `skills/github-workflow/SKILL.md` §1 documents the flag next to the existing
      `check_pr_body.py` invocation and next to the "Every number in a body belongs to one
      commit" rule added there on 2026-08-01; `CONTRIBUTING.md` unchanged unless the CI
      backstop lands with it.
- [ ] The scope limit is written down where an author will read it: timings and prose
      *behavioural* claims are NOT covered. (Test counts were moved out of this list on
      2026-08-01 — they are covered. Diff sizes were moved out on 2026-08-01 by Round three —
      they come from `git` and are covered.)
- [ ] **Nothing in this task is closed by new wording.** Round three measured three separate
      written warnings failing, one of them inside the pass that wrote it. A `SKILL.md` /
      `CONTRIBUTING.md` / template edit may accompany the checker but never substitutes for it,
      and "the rule is now clearer" is not a Definition-of-done item.
- [ ] Decided and recorded, either way: whether the CI backstop (`gh pr view` + `edited`
      trigger) is in this task or a follow-up.
- [ ] Re-checked against the round-two **and round-three** tables above: the finished checker
      flags all nine false `verify_links` counts, #161's reconcile count, all four stale suite
      counts, #174's `2658 … 1244`, #175's `2670` at a correctly-named commit, and #173's two
      diff-size/file-count claims. A fix that does not catch the rounds it was written for is
      not done.
