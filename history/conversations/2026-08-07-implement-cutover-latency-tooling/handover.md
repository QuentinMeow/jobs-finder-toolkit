# Handover — implement-cutover-latency-tooling

- **Date**: 2026-08-07
- **Task(s)**: [2026-08-07-reduce-agent-development-cycle-latency](../../../tasks/1_in-progress/2026-08-07-reduce-agent-development-cycle-latency/task.md)

## What happened

- Nothing is on fire and nothing is half-done. One commit on
  `codex/reduce-agent-development-cycle-latency`; maintenance 9/9, policy 8/8, full pre-commit
  chain green. Not pushed — no PR opened yet.
- The P1 latency task went from documentation to working tooling: opt-in phase telemetry, a
  read-only two-repository cutover planner, a validation profile, a pinned benchmark fixture, and a
  routed fast path. The guarded executor was deliberately left unbuilt.
- Depth is in the task folder: [verification.md](../../../tasks/1_in-progress/2026-08-07-reduce-agent-development-cycle-latency/verification.md)
  carries the gate block, the defect table, and an honest per-item DoD status.

## Where things stand

- Committed locally, unpushed. Three DoD items are open by design and named in `verification.md`:
  the ≥3-run baseline, solution step 5 (closeout tax), and the end-to-end 50% improvement — which
  is **not reachable from this scope**, because steps 2–4 touch under ~5 minutes of the 27m33s.
  Closing it needs telemetry to locate the unattributed 8m17s plus the 7m03s closeout work.
- The task stays in `1_in-progress/` for that reason.

## Decisions made for you

- **The guarded executor was not built.** Reflogs bound checkpoint-and-replay at 2m38s of 27m33s
  (9.6%), and the executor explicitly refuses the conflict resolution that consumed most of that
  window — so ~10% of the clock for 100% of the blast radius, on the two repos holding your live
  job hunt. This one was expensive enough to reverse that it is a queue item, not just this line:
  [cutover-executor-deferred-until-telemetry](../../../message-queue/needs-human/decisions/cutover-executor-deferred-until-telemetry.md).
  Undoing costs only the build — the design is written and
  [the task is filed](../../../tasks/0_backlog/2026-08-07-guarded-cutover-executor/task.md).
- **Nothing new is called "reconcile".** The new tools live in `automation/cutover/`, because an
  agent told to "run the reconciler" must reach the process-layer schema gate, not a git-state
  planner. A test pins the disambiguation line in both `--help` and the handbook page.
- **`summarise()` grew an additive `require_pass` flag** rather than changing the repo lanes'
  semantics: an all-SKIP run is legitimately green for the lanes and never green for a profile whose
  job is to prove something. Default is off, so `run_gates` behaves exactly as before.
- **The plan JSON rolls up ignored paths with no merged-layout counterpart** (72 MB → 53 KB).
  Everything actionable keeps a full entry, including every ignored path that DOES need copying.
  `--full-json` reverses it.

## If X then Y

- **If you turn the recorder on for one real post-merge session, that decides the next move.**
  `mutation` large → build the executor. `external_wait` large → extend the completed
  [CI/stack latency work](../../../tasks/4_done/2026-08-03-reduce-pr-ci-and-stack-latency/task.md)
  instead. `closeout` large → solution step 5 first. Do not build all three.
- If the `cutover` validation profile shows `app-metadata` red, that is pre-existing (7 of 274
  applications), not something this work broke — [filed](../../../tasks/0_backlog/2026-08-07-seven-applications-fail-metadata-validation/task.md).
- If `bootstrap_overlay --check` says "the leak guard does not run on commit or push here", it is
  currently wrong: your overlay hooks are symlinks that resolve and are executable, so the guard
  **is** running. Verified by hand; [filed](../../../tasks/0_backlog/2026-08-07-bootstrap-says-the-leak-guard-is-off-when-it-is-running/task.md).
  Running `bootstrap_overlay.py` without `--check` migrates them to managed copies and clears it.

## Dead ends

- **Four parallel agents each appending a review-ledger row does not work.** Each row pins a digest
  of the diff at its own base; concatenating four of them at merge time orphans three, and
  `review_gate --verify-all` recomputes every historical row in CI. One row at the integration tip
  is the only shape that survives. One agent correctly refused to append a row at all and stopped
  with its work staged rather than guess — that was the right call.
- **Green gates proved nothing about correctness.** All 9 maintenance gates were green *before* the
  adversarial pass found five defects, two of which were "report a failed thing as green" — the
  exact guardrail this tooling exists to protect. Do not skip the adversarial pass on the theory
  that the suite is green.

## Needs your attention

- [cutover-executor-deferred-until-telemetry](../../../message-queue/needs-human/decisions/cutover-executor-deferred-until-telemetry.md)
  — **Why this matters:** it overturns or confirms a DoD item you wrote. **If you do nothing:** the
  executor stays unbuilt, the planner keeps emitting the mechanical steps as data, and an agent
  performs them by hand guided by the plan. Nothing degrades.
- The branch is **not pushed and no PR is open** — say the word and it goes up through
  `skills/github-workflow/`.
- Older items are unchanged; the `needs-human/decisions/` queue was not folded this session.
