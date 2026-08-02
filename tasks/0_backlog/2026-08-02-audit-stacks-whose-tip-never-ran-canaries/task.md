# Audit merged stacks whose named tip never ran its canaries

- **Priority**: P1 (this round)
- **Area**: harness
- **Source**: PR #196 (`Eval gate: stack` discharge form) — its own "what this cannot verify" section, 2026-08-02
- **Claimed-by**:

## Goal

Make the one honest detection path for a deferred stack run **mechanical** instead of a human
procedure, so a stack that defers its canary run and then never performs it is discovered rather
than merely discoverable.

## Context

PR #196 added a fourth way to discharge the eval gate. An intermediate PR in a stack may write:

```
Eval gate: stack — <why this one is intermediate>; tip: <#PR | branch | pull URL>
```

`check_pr_body.py --eval-gate-only` accepts it only when a tip is actually named. That is all it
can do, and the reason is structural rather than an oversight:

- At the intermediate PR's CI time the tip's run **does not exist yet**, and the `pr-body` job never
  reads another PR's body.
- **The tip is not automatically bound either.** `.github/workflows/ci.yml` computes changed files
  as `git diff --name-only $(git merge-base "$BASE_SHA" "$HEAD_SHA") "$HEAD_SHA"`. For a stacked PR,
  `base.sha` is *the branch below*, so the tip's diff contains only the tip's own commits. If the
  tip's own diff touches no `skills/*/{SKILL,LESSONS,reference}.md`, **gate 11 never fires on it and
  nothing forces the run.** PR #196 verified this against its own changed-file list rather than
  assuming it. The tip is bound only when its own diff happens to touch an instruction file.

So a stack can legitimately defer, merge every rung, and never run anything — with every individual
CI check green. The documented mitigation is an audit: grep merged PR bodies for `Eval gate: stack`
and check each named tip. No tooling exists for it, and an undetectable obligation with no owner
eventually reads as a discharged one.

Rejected in #196 and **not** worth revisiting: having CI resolve the named PR through the API at
merge time. The tip usually does not exist when the intermediate is checked, a body can change after
the check, and fork PRs get no token.

The accepted forms and the audit obligation are stated in `evals/README.md`, gate 11 of
`skills/github-workflow/SKILL.md`, `CONTRIBUTING.md`, `AGENTS.md`, and a comment beside the CI job.
Any change here must keep those five surfaces in agreement.

**Placement — a recommendation, not a decision.** `automation/gardener/` already runs dry-run
hygiene sweeps over the repo and reports rather than blocks, which matches this exactly: the finding
is historical, it cannot block anything at merge time, and it wants a periodic report. Beside
`check_pr_body.py` is the alternative, and it keeps the eval-gate logic in one place — but that
script is a per-PR body checker that CI invokes, and this is a repo-wide retrospective sweep, so the
shapes do not match. Note also that a live decision
(`message-queue/needs-human/decisions/process-weight-what-to-cut.md`) has a default path forbidding
**new gates** while it is open — so whatever is built must report, not block, unless that decision
has been answered by then.

## Definition of done

- A command exists that lists every merged PR whose body carries an `Eval gate: stack` line, with
  the tip each one named.
- For each such tip it reports one of: **ran** (the tip's body carries canary results or names a
  filed `evals/results/…md` record), **owed** (an open `tasks/0_backlog/` item covers the stack), or
  **UNDISCHARGED** — and exits non-zero only in a mode the operator opts into, never by default while
  `process-weight-what-to-cut.md` is unanswered.
- The two degenerate cases are handled explicitly and covered by a test: a named tip PR that was
  **never opened**, and one that was **closed without merging**. Both must report `UNDISCHARGED`
  rather than crashing or silently passing.
- Running it against this repo's real history produces a result, and that result is pasted into the
  task's `worklog.md` — including the current count of undischarged stacks, which is the number this
  task exists to make visible.
- Tests live beside the tool and match its neighbours' conventions; `automation/reconcile/reconcile.py --check`
  and `automation/publish/review_gate.py` both still exit 0.
