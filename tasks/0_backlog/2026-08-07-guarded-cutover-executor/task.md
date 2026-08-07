# Guarded executor for the mechanical cutover steps

- **Priority**: P2 (someday) — gated on phase telemetry, deliberately not P1
- **Area**: harness
- **Source**: Descoped from
  [2026-08-07-reduce-agent-development-cycle-latency](../../1_in-progress/2026-08-07-reduce-agent-development-cycle-latency/task.md)
  (its solution step 3, first half). Design already written and reviewed; only the build is deferred.
- **Claimed-by**: <(set when work starts, before the first change)>

## Goal

Once phase telemetry shows that local mutation time is actually worth attacking, add
`automation/cutover/apply_cutover.py`: a guarded executor that performs only the plan's proven
mechanical steps (recoverable checkpoint, replay across the resolved base, verified path rewrites,
selected validations), leaves publication to `skills/github-workflow/`, and prints a recovery ref
for every mutation.

## Context

**Why it was deferred rather than built.** The parent task's own audit handover states the ordering
rule: instrumentation first, then choose the optimization the data supports. The reflog evidence
bounds the checkpoint-and-replay window at **2m38s of the 27m33s run — 9.6%**, and the executor
explicitly refuses the conflict resolution that consumed most of that window, so its realistic
ceiling is well under two minutes. Against that, it is the only proposed component that rebases two
real repositories containing the owner's live job hunt, unattended: roughly 10% of the clock for
100% of the blast radius, before any telemetry says it is even the right 10%.

**What already shipped** (so this task is a build, not a design):

- `automation/cutover/plan_cutover.py` emits the mechanical steps as data — each with `recovery_ref`
  under `refs/cutover/<run-id>/…`, `recovery_argv`, and a `preconditions` list (`head-oid`,
  `no-in-progress-op`, `worktree-set-digest`, `dirty-blob-digest`). The executor's job is to
  re-verify those preconditions immediately before acting and then run the step.
- `automation/cutover/validate_cutover.py` is the post-mutation validation profile.
- The full executor contract — permitted operations, refusals, resumability, recovery refs — is
  section 5 of the design at
  `docs/handbook/post-merge-cutover.md` plus the parent task's "Suggested solution sequence" #3.

**Revisit condition.** Take this task when phase telemetry from
`automation/metrics/phase_summary.py` shows `mutation` is a material share of a real
post-merge session. If telemetry instead shows `external_wait` dominates, extend the completed
[PR/CI latency work](../../4_done/2026-08-03-reduce-pr-ci-and-stack-latency/task.md) instead; if
`closeout` dominates, take solution step 5 (closeout tax) first.

## Definition of done

- [ ] Phase telemetry from at least one real post-merge session is attached, showing `mutation`
  time large enough to justify the work.
- [ ] `apply_cutover.py` performs only steps the plan marked `kind: mechanical`, and refuses
  anything else.
- [ ] Every mutation is resumable and prints its recovery ref before acting.
- [ ] Tests prove it never deletes owner files, never overwrites an ignored copy, never bypasses a
  red gate, and never reports a failed command as green.
- [ ] Content conflicts remain agent work — the executor refuses them.
