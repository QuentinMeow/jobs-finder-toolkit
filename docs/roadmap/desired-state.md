# Desired state (priority order)

1. **Email-driven application progress** (`design/application-progress-calendar/execution-plan.md`):
   a provider-bounded, draft-only email layer that downloads mail into the
   local store, categorizes job-related messages, and turns them into
   guarded progress + calendar proposals — replacing repeated live mailbox
   reads after a proven side-by-side period. Stages 1–5 map to the four
   email tasks in `tasks/0_backlog/`.
2. **Structured progress + calendar as first-class tracker state**
   (meta.yaml schema v5, `calendar.md`, `status.py --update-progress` /
   `--sync-calendar`) without changing the coarse status-folder pipeline.
3. **Raw-data-layer store as the single job-postings substrate**
   (`design/raw-data-layer/execution-plan.md`): remaining work is the
   incremental O(new) build (`tasks/0_backlog/2026-07-21-store-incremental-build-o-new`)
   and the parked logs-as-projections question
   (`message-queue/needs-human/decisions/logs-as-store-projections.md`).
4. **A self-enforcing process layer** (AgentFold restructure): reconciler
   green in pre-commit + CI, queue hygiene tooling
   (`tasks/0_backlog/2026-07-21-todo-queue-hygiene-tooling`), tree-instructions
   validator, and session handovers in `history/`.
5. **Benchmark and eval depth**: stage-fixtures v2, remaining canary
   additions (blacklist registry rewrite, bundled-txt naming, v3 rejection
   fixture), and the parked benchmark rows in the private mirror.
