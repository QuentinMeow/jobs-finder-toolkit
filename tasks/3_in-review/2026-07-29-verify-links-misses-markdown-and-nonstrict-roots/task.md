# verify_links.py checks neither markdown links nor refs at unknown roots

- **Priority**: P1 (this round) — **scheduled next by the owner on 2026-07-29, ahead of workspace
  phase 5.** Phase 5 removes `interviews/` from `SKIP_PREFIXES` and repairs the 244 relative
  markdown links inside that tree; because this checker reads no markdown links at all, that
  repair would report success whether or not it worked. Fixing the checker first turns phase 5's
  largest verification step from unverifiable into verifiable, and doing it afterwards means
  doing the link work twice. Recorded as a blocking precondition on
  [the phase-5 task](../2026-07-28-workspace-phase-5-lifetime-taxonomy/task.md).
- **Area**: harness
- **Source**: workspace phase 2, 2026-07-29 — [the phase-2 record](../../../docs/designs/workspace-restructure/execution-plan.md#merged-phase-2--public-side-cleanup) and [its verification](../../3_in-review/2026-07-28-workspace-phase-2-public-cleanup/verification.md)
- **Claimed-by**: agent, 2026-07-29 — see [verification.md](verification.md) and
  [worklog.md](worklog.md). Three of this file's numbers were wrong and are corrected in
  the Definition of done below; the reasoning is in the worklog rather than rewritten
  over the original text.

## Goal

Make `automation/gardener/verify_links.py` see the two whole classes of reference it is blind to
today, so a rename cannot break links while the gate reports "references: all resolve".

## A third case, found while filing this task

**Folding a queue item into an ADR kills every inbound link from dated records.** `AGENTS.md`'s
folding ritual ends "delete the queue file", and nothing in it says what happens to the handovers
that linked it. Recording the config-discovery answer on 2026-07-29 deleted one queue file and
broke its link in **five** `history/conversations/*/handover.md` records in a single commit —
measured, not estimated. The handovers are dated records and rewriting them would falsify
history, so those five links are staying broken.

This is not a bug in the folding ritual; it is a gap in what a link checker should *mean*. Decide
a policy here rather than inheriting one by accident. Two shapes worth weighing: resolve a dead
link through its successor when the ADR names what it replaces (the ADR written that day does say
which queue file it replaces, so the information exists), or treat links whose *source* is a dated
record as advisory the way `PLAN_OR_RECORD_SOURCES` already treats backticked refs — noting that
the second choice means a record can rot silently, which is the failure this whole task exists to
close. Whatever is chosen, the count above is a live example to test against.

## Context

One file, one checker, two gaps in the same universe-of-things-it-looks-at. They are filed
together because fixing either one alone still leaves the checker able to report a clean tree
while links are broken.

**Gap one: it never checks markdown links.** `check_references()` only inspects **backticked**
tokens (`BACKTICK_RE`), and `_is_checkable()` rejects any token containing `(` or `)`. So every
`[text](path)` link in every tracked `.md` is unverified. Measured with a throwaway checker that
resolves each relative link target against its own file's directory:

```
$ python mdlinks.py <worktree at d9aa3cb>   # base of the phase-2 stack
TOTAL BROKEN RELATIVE LINKS: 36
$ python mdlinks.py .                       # tip of the phase-2 stack
TOTAL BROKEN RELATIVE LINKS: 31
```

**Between 31 and 36 broken relative markdown links stand in the tree right now, and no two
checkers agree on which.** The count fell across the phase on every checker tried. A second,
independently written checker measured 36 on `main` and 33 at the stack tip. Throughout all of it
the gardener reported "references: all resolve".

**A warning for whoever picks this up: do not trust the set-churn figure.** Comparing the two
inventories suggests the sets share almost no entries — 36 repaired, 31 fresh — which reads as
though the phase broke as much as it fixed. It did not. The comparison keys each entry on
`<source file> -> <target>`, and phase 2 *moved most of the source files*, so a pre-existing break
inside `handbook/foo.md` reappears as a brand-new break inside `docs/handbook/foo.md`. Spot-checks
of the "fresh" entries found them to be prose examples like `` [text](path) ``, links into the
overlay that a detached worktree cannot resolve, or targets such as `migration.md` that have never
existed in any commit. **Whatever this task builds must be able to follow a rename**, or its first
run after any move will report a repo-wide regression that did not happen.

**Gap two: a backticked ref at a root the checker does not recognise is invisible** — not broken,
not advisory, not counted in any skip tally. `check_references()`
(`automation/gardener/verify_links.py:249-252`) records an unresolved token only when it starts
with an *absent* strict root or a *present* one; anything else falls out of the loop with no
counter touched. Reproduced on this tree by planting the same broken reference twice:

```
$ printf '\nSee `docs/handbook/definitely-not-a-real-file.md` for details.\n' >> docs/handbook/file-organization.md
$ .venv/bin/python automation/gardener/verify_links.py; echo "exit=$?"
  BROKEN references: 1
  FAIL: broken references / symlinks / drift found.
exit=1

$ printf '\nSee `handbook/definitely-not-a-real-file.md` for details.\n' >> docs/handbook/file-organization.md
$ .venv/bin/python automation/gardener/verify_links.py; echo "exit=$?"
  references: all resolve
  OK: links, symlinks, and vendored copies verified.
exit=0
```

**76 references at the four root names phase 2 retired** (`handbook/`, `design/`, `roadmap/`,
`tmp/`) survive across 24 tracked files and are in that hole today. This is a pre-existing
structural property of the checker, not something the moves introduced — but every root rename
widens its blast radius, and phases 5 through 8 rename more roots.

The workspace plan already names the wholesale version of this hazard ("renaming a root that a
checker names in a constant disarms the checker instead of breaking it"). What phase 2 found is
the retail version: references drop out one at a time, and no count moves.

**Do not simply make every unknown-root ref hard-fail.** The reason the fall-through exists is
that most bare-relative tokens (`scripts/x.py`, `source/…`, `_vendor/…`) are skill-relative or
documented-optional and legitimately resolve under a non-root base — see `_bases_for()` and the
comment above `STRICT_ROOT_PREFIXES`. Making them visible is the requirement; making them fatal
is a separate decision. Counting them (a `skipped["unrecognised-root"]` tally printed like the
other three) is the minimum that closes the silent part.

Note also that `PLAN_OR_RECORD_SOURCES` routes findings from `docs/designs/`, `tasks/`,
`message-queue/`, `history/`, `memory/decisions/` and `evals/results/` to an advisory list rather
than a failure — deliberately, because those docs name target and historical paths. Markdown-link
checking must respect the same split, or every dated record becomes a build break. That split is
also the open question in the 21 remaining broken links: a `Source:` line in a task file is
navigation and should be repaired, while a handover quoting a path that was true at the time is a
record and should not. Decide the rule, don't repair case by case.

## Definition of done

- [x] `verify_links.py` resolves relative `[text](path)` targets in every tracked `.md` —
      plus images, reference-style links and HTML `href`/`src` — under a **three**-tier
      split (reference fails, plan is advisory, dated record is permitted), not the
      two-tier one this file assumed
- [x] A ref matching no strict prefix is **counted and reported** rather than dropped; the
      "not strict, not absent" fall-through now increments `skipped["unrecognised-root"]`
      and records the ref for `--list-unrecognised`. **953, not the 76 estimated here**
- [x] `automation/gardener/tests/test_verify_links.py` gains a regression for each, plus
      the wrapped-code-span case that a per-line implementation fails and every other
      test passes
- [x] **23**, not 21, and **every one is in a dated record** — so the deliverable is not a
      repair campaign but a written rule that says so. Two genuine breaks outside that
      tier were repaired: a stale heading anchor in the handbook, and a retired
      `automation/maintenance/` path inside the overlay
- [x] `verify_links.py` is clean, in both the overlay-mounted and `--no-overlay` views,
      and two independently written markdown-link checkers agree with it row for row
- [x] **Added, not in the original scope:** the routine now runs in CI and pre-commit (it
      ran in neither), it enumerates the overlay's tracked markdown (it never had), and
      `--baseline`/`--compare` follow renames through both repositories' rename maps so a
      move cannot report a regression that did not happen
