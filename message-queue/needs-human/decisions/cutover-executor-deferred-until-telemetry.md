# Should the guarded cutover executor ship now, or wait for phase telemetry?

- **Status**: awaiting-owner-input
- **Filed**: 2026-08-07
- **Source**: [reduce-agent-development-cycle-latency](../../../tasks/1_in-progress/2026-08-07-reduce-agent-development-cycle-latency/task.md)
- **Blocks**: nothing. The planner, validation profile, recorder, fixture, and fast path all
  shipped; only the mutating executor is held back.
- **Default path**: the executor is NOT built. `plan_cutover.py` emits the mechanical steps as
  data (each with a recovery ref and preconditions) and the agent performs them by hand, guided by
  the plan. Filed as [2026-08-07-guarded-cutover-executor](../../../tasks/0_backlog/2026-08-07-guarded-cutover-executor/task.md).
- **Cost if wrong**: one-time — a later session builds it against a design that is already written.
- **Safe to merge because**: nothing was written that assumes an executor. No file references
  `apply_cutover.py`; a test asserts no benchmark stage runs a mutating git verb. Building it later
  is additive, and un-deferring costs only the build.
- **Revisit when**: phase telemetry from a real post-merge session shows `mutation` is a material
  share of the clock.

## Background

The parent task's definition of done lists a guarded executor that performs the plan's mechanical
steps: checkpoint, replay across the resolved base, apply verified path rewrites, run validations.
Its design was written and reviewed alongside the planner's. I did not build it, and that is a
departure from a definition of done you wrote, so it is yours to confirm or overturn.

The measurement that drove the call: reflogs bound the checkpoint-and-replay window of the 27m33s
run at **2m38s — 9.6% of the total**. The executor also explicitly refuses content-conflict
resolution, which consumed most of that window, so its realistic ceiling is well under two minutes.
It is simultaneously the only component that would rebase two real repositories containing your live
job hunt, unattended. The task's own audit handover states the rule directly: instrument first, then
let the data pick the optimization ("if GitHub wait dominates, extend the CI work *instead of*
building a local executor").

## Options

The axis is time-to-capability against evidence-before-blast-radius.

### Option A — leave it deferred until telemetry justifies it (the default path)

Build it only when `phase_summary.py` shows `mutation` is worth attacking. The planner already
emits every mechanical step with its recovery ref, so the manual path is guided rather than
reconstructed — which was the actual complaint in the audit.

***Example consequence:*** Your next post-merge session runs one read-only command, reads a table
that already says which dirty paths were moved and which need copying, and you run four or five
git commands it printed. You save most of the discovery time and none of the typing time.

### Option B — build it next round anyway

Accept the ~10%-of-clock ceiling and get the typing automated too.

***Example consequence:*** A session where the executor's precondition check races something you
changed in another window, and it stops halfway with a recovery ref you now have to reason about —
on the repository holding your applications. Recoverable, but it is a worse ten minutes than the
ten minutes it saved.

## Recommendation

Keep it deferred. The planner and validation profile carry nearly all of the measured value at
essentially no risk, and the executor is the one piece whose value is unproven *and* whose blast
radius is your real data. If telemetry later shows mutation time matters, the design is written and
the build is short.

**Strongest case against this:** the 2m38s figure is a floor, not a ceiling — reflogs only see
ref-changing events, so every read, status check, and half-finished command inside that window is
invisible. The true mutation-phase cost could be several times larger, and the very telemetry I am
waiting for is telemetry nobody may ever remember to turn on. If that is how it plays out, deferring
means the executor never gets built for a reason that was never actually tested.

**Confidence:** medium — I verified the reflog window and that the executor's design excludes
conflict resolution, and I confirmed the planner emits every mechanical step with a recovery ref. I
did NOT measure how long the manual mechanical steps actually take, because no phase telemetry
existed until this task shipped it.

**Your answer:** ______
