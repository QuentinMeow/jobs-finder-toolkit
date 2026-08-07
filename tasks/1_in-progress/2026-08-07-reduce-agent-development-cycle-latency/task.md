# Reduce agent development-cycle latency for post-merge reconciliation

- **Priority**: P1 (this round)
- **Area**: harness
- **Source**: Owner-supplied Codex screenshot reporting 27m33s for the 2026-08-07 post-merge local reconciliation; corroborating Git reflogs, commit history, and [session handover](../../../history/conversations/2026-08-07-reconcile-local-work-after-private-refactor/handover.md)
- **Claimed-by**: Claude Code, repo root (2026-08-07)

## Goal

Make the common "the prerequisite PRs merged; reconcile preserved local work and publish the
remainder" workflow measurably faster without deleting owner data, weakening gates, or hiding
external wait time. The result should give agents one fail-closed path from inventory through
handoff instead of reconstructing the same two-repository procedure each session.

## Context

### What the 27m33s run actually delivered

The run was larger than local branch cleanup. It:

- updated the public and nested private repositories after two prerequisite PRs merged;
- preserved and checkpointed an unrelated dirty private patch;
- replayed that patch across a person-first folder migration and resolved a generated-calendar
  conflict only after proving the migration's relevant delta was path-only;
- validated private application metadata, the generated calendar, configured paths, and an
  ignored-file copy without deleting the retired source;
- opened and merged private PR #94;
- created the public closeout commit, opened and merged public PR #322, updated the task state,
  and recorded the handover and owner-only deletion decision; and
- removed task-owned temporary worktrees and returned both mounted repositories to clean `main`.

Those outcomes were correct and the safety work was warranted. The performance failure is that the
workflow exposed none of its phase timings while it ran, repeated manual discovery and publication
steps, and paid a large tracked-bookkeeping cost after the functional reconciliation had finished.

### Evidence and limits

The Codex UI supplies the only complete elapsed-time measurement: **27m33s**. Git reflogs expose
only ref-changing events, so they account for **19m16s**, from the private branch checkout at
03:56:37 through the final public fast-forward at 04:15:53. Reads, status checks, validation
commands, approval waits, network calls, and reasoning leave no reflog event. Consequently,
**8m17s of the user-visible total is unattributed**; assigning it to a specific activity would be
fabrication.

The visible intervals are coarse bounds, not command-level timings:

| Interval | Reflog evidence | Elapsed | What can be concluded |
|----------|------------------|---------|-----------------------|
| Before first ref mutation | UI total minus the ref-visible window | ~8m17s | The current telemetry cannot distinguish context loading, inventory, reasoning, tool retries, or waiting. This is the largest unknown. |
| Private checkpoint and replay | checkout 03:56:37 → rebase complete 03:59:15 | 2m38s | Git preserved the dirty patch and replayed it across the new layout. The conflict-resolution commands inside the interval are not timed. |
| Private publication window | rebase complete 03:59:15 → private `main` fast-forward 04:04:03 | 4m48s | Validation, PR creation, merge-driver work, remote waiting, and local update share one interval. |
| Post-merge cutover and public closeout preparation | private fast-forward 04:04:03 → public closeout commit 04:11:06 | 7m03s | Local config/copy verification, worktree cleanup, task closure, roadmap, review ledger, queue decision, verification, worklog, and handover occurred here. The closeout commit added 156 lines and removed seven across seven files. |
| Public publication window | closeout commit 04:11:06 → public `main` fast-forward 04:15:53 | 4m47s | Push, PR creation, required checks, merge, and update share one interval. Existing hosted evidence says a process-only PR can finish CI in 36s with a separate 9s PR-body job, so CI alone does not explain this window. |

The earlier [PR/CI latency task](../../4_done/2026-08-03-reduce-pr-ci-and-stack-latency/task.md)
optimized hosted checks and stack merging. This task concerns **agent orchestration latency**:
discovering state, choosing the safe path, performing the local two-repository reconciliation,
and producing required records. It should reuse the existing hosted measurements rather than
reopen that completed design.

### Issues to solve

1. **No Codex phase telemetry.** The optional collector in
   [`docs/handbook/metrics.md`](../../../docs/handbook/metrics.md) is described for Claude Code
   session hooks and records session/tool totals, not named workflow phases or active-versus-wait
   time. The largest interval in this case is therefore unknowable.
2. **Manual two-repository inventory.** An agent must independently inspect branches, worktrees,
   dirty files, remotes, merged heads, config paths, and path rewrites in the public and nested
   private repositories. The evidence is gathered by many commands and then reconstructed in
   reasoning instead of emitted as one deterministic plan.
3. **Serial work that is only partly dependent.** The private replay depends on the merged public
   layout, but public/private fetches, read-only inventories, independent validation commands, PR
   body preparation, and some closeout drafting do not need to wait on one another.
4. **Safety checks are correct but manually assembled.** Checkpointing, rename verification,
   configured-path checks, calendar validation, metadata validation, non-overwriting ignored-file
   copy, checksum comparison, and worktree cleanup are repeatable mechanics. Manual assembly costs
   time and makes omissions more likely.
5. **Process records arrive late and create a second publication cycle.** The functional private
   reconciliation was complete before the public task, roadmap, ledger, queue, verification,
   worklog, and handover commit. The current contract makes those records valuable, but their
   volume and timing turn closeout into another multi-minute PR lifecycle.
6. **The read path is broad for a narrow continuation.** The root contract, queue boot ritual,
   memory index, GitHub workflow, task history, and private-overlay context may all be relevant,
   but the repository has no documented fast path for this exact post-merge continuation. Whether
   repeated reading was a material contributor was not measured and must remain a hypothesis until
   phase telemetry exists.

### Suggested solution sequence

#### 1. Instrument before optimizing

Extend the local metrics system with a Codex-compatible, opt-in phase recorder using monotonic
time. At minimum record `inventory`, `context`, `plan`, `mutation`, `validation`, `commit`,
`publish`, `external_wait`, and `closeout`, with repository, command/tool count, outcome, and a
session correlation id. Store raw events only in an ignored local path and generate a redacted
summary suitable for a task verification record.

Active agent time, approval wait, GitHub/CI wait, and subprocess runtime must be separate numbers.
A faster CI run is not evidence of faster reasoning, and a slow approval response is not evidence
of a slow script.

#### 2. Add a read-only post-merge reconciliation planner

Provide one command that inspects the public root and configured private overlay together and emits
a deterministic plan. It should:

- fetch both remotes concurrently when authorized, otherwise label remote knowledge stale;
- list each repository's base, branch, upstream, worktrees, dirty paths, and ahead/behind counts;
- identify which prerequisite commits are already reachable from each `origin/main`;
- classify dirty paths as unchanged, renamed by the merged layout, content-divergent, ignored, or
  unknown using Git object ids and `-M100%` rename evidence;
- show the exact proposed checkpoint, replay, validation, and publication steps without mutating;
- stop on unknown paths, content conflicts, missing remotes, or ambiguous ownership; and
- emit machine-readable JSON beside the human table so later steps do not rediscover the state.

This planner must never delete owner data or infer that an ignored source is disposable.

#### 3. Add a guarded execution path for mechanical cases

Once the plan is accepted, a separate command may perform only the plan's proven mechanical steps:
create a recoverable checkpoint branch/commit, replay across the resolved base, apply verified path
rewrites, run the selected validations, and leave publication to the existing GitHub workflow.
Content conflicts remain agent work. Every mutation should be resumable and print its recovery ref.

Bundle the application metadata, calendar, configured-path, and checksum checks behind a named
validation profile so one command produces one set of exit codes. Independent checks should run in
parallel while preserving each real exit code.

#### 4. Create a narrow continuation fast path

Document a routed read order for a request whose prerequisites are already merged and whose goal is
to reconcile preserved local work. The path should read the prior task/handover, the relevant
GitHub cleanup/publish section, and the planner output first; it should open broader memory or design
documents only when the planner finds a condition that requires them. Queue filenames are still
listed, hard guardrails still apply, and unknown scope still fails closed.

#### 5. Reduce closeout tax without losing durable state

Evaluate two compatible options:

- mechanically generate the task/worklog/verification/handover deltas from the execution record,
  leaving the agent to add only decisions and unresolved risks; or
- define a compact local-reconciliation closeout profile where one task update plus one handover
  satisfies the process layer unless architecture, roadmap truth, or an owner decision changed.

The implementation must update templates and reconciler checks together if it changes a schema.
It must not suppress the leak guard, review ledger, owner-deletion rule, or required unresolved-item
routing merely to save time.

#### 6. Parallelize the remaining independent work

Run public/private read-only inventory and fetch concurrently, run independent validation lanes
concurrently, and prepare reviewer-facing text while required remote checks execute. Keep the
private replay after the public base is resolved and keep irreversible merge/delete operations
serialized and revalidated immediately before execution.

### Benchmark scenario

Use a pinned synthetic fixture containing:

- a public repository whose layout refactor is already merged;
- a nested private overlay with a small dirty patch authored against the old paths;
- one generated-file path-only conflict;
- one ignored file that must be copied non-overwriting and retained at the source; and
- public and private closeout records requiring normal gates.

Benchmark stages independently in accordance with
[`fine-grained-stage-benchmarks.md`](../../../memory/decisions/fine-grained-stage-benchmarks.md),
then run the end-to-end confirmation. The real 27m33s observation is motivation, not a statistically
valid baseline.

## Definition of done

- [ ] A Codex-compatible recorder attributes at least 95% of elapsed time to named phases and
  reports active, subprocess, approval, and external wait separately.
- [ ] The pinned fixture and baseline include at least three current-path runs; median and range are
  recorded for every phase rather than only end to end.
- [ ] One read-only command produces the complete two-repository reconciliation plan and fails
  closed on unknown, divergent, missing-remote, or worktree-owned states.
- [ ] A guarded executor handles the fixture's mechanical checkpoint/replay/validation path and
  leaves a recoverable ref for every mutation.
- [ ] Tests prove the planner/executor never delete owner files, never overwrite ignored copies,
  never bypass a red gate, and never report a failed command as green.
- [ ] The routed fast path and closeout policy are documented, with any template/schema changes
  accompanied by matching reconciler tests and migrations.
- [ ] Across at least three optimized fixture runs, median non-external elapsed time is at least 50%
  below the measured current-path median and no more than 10 minutes; external GitHub/approval wait
  is reported beside, not hidden inside, that result.
- [ ] A final real-session comparison records wall clock, active time, tool calls, repeated file
  reads, validation time, publication time, and the exact gates preserved.
