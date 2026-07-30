# verify_links.py checks neither markdown links nor refs at unknown roots

- **Priority**: P1 (this round)
- **Area**: harness
- **Source**: workspace phase 2, 2026-07-29 — [the phase-2 record](../../../docs/designs/workspace-restructure/execution-plan.md#merged-phase-2--public-side-cleanup) and [its verification](../../3_in-review/2026-07-28-workspace-phase-2-public-cleanup/verification.md)
- **Claimed-by**:

## Goal

Make `automation/gardener/verify_links.py` see the two whole classes of reference it is blind to
today, so a rename cannot break links while the gate reports "references: all resolve".

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

**31 broken relative markdown links stand in the tree right now.** The count fell across the
phase, but the two sets share not one entry: 36 pre-existing breaks were repaired and 31 fresh
ones appeared, nearly all `design/` → `docs/designs/` misses in dated records and task files. The
phase-2 record PR repaired 10 of the 31 (seven in the execution plan, three in the phase-2 task
file); the remaining 21 are the starting inventory for this task. Throughout all of it the
gardener reported "references: all resolve".

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

- [ ] `verify_links.py` resolves relative `[text](path)` targets in every tracked `.md`, using
      the same advisory/hard-fail split as backticked refs
- [ ] A ref matching no strict prefix is **counted and reported** rather than dropped; the
      "not strict, not absent" fall-through touches a tally
- [ ] `automation/gardener/tests/test_verify_links.py` gains a regression for each: a planted
      broken `[text](path)` link fails, and a planted broken ref at an unrecognised root is
      visible in the output
- [ ] The 21 remaining broken markdown links are triaged under a written record-vs-reference
      rule, and the repairable ones repaired
- [ ] `.venv/bin/python automation/gardener/verify_links.py` is clean on the resulting tree, and
      a fresh run of a throwaway markdown-link checker agrees with it
