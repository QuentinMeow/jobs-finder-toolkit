# Desired state (priority order)

1. **Email-driven application progress** (`docs/designs/application-progress-calendar/execution-plan.md`):
   a provider-bounded, draft-only email layer that downloads mail into the
   local store, categorizes job-related messages, and turns them into
   guarded progress + calendar proposals — replacing repeated live mailbox
   reads after a proven side-by-side period. **Where the work actually is,
   re-checked 2026-07-31 — there are zero email tasks in `tasks/0_backlog/`:**
   stage 1 (`2026-07-22-email-provider-contract`) and stage 3
   (`2026-07-22-email-store-sync`) are in `tasks/3_in-review/`, both held for
   missing definition-of-done evidence; stage 2 is merged
   (`tasks/4_done/2026-07-23-email-notes-calendar-reconciliation`); stage 4
   (`2026-07-22-email-progress-reconciliation`) is the one genuinely in flight,
   in `tasks/1_in-progress/`; and **stage 5 — the store-first review cutover —
   has no task file at all**, only the design's own section. The top-priority
   item on this list therefore points at nothing for its final stage. Filing
   that task is gated on stage 4 landing, and on the dual criterion recorded in
   `memory/decisions/raw-data-layer-decisions.md` row 14 (five consecutive
   zero-mismatch store-vs-live runs **and** ≥300 job-related messages through
   both paths), for which no comparison-run record exists anywhere yet.
2. **Structured progress + calendar as first-class tracker state**
   (meta.yaml schema v6 with multi-occurrence calendar links, `calendar.md`, `status.py --update-progress` /
   `--sync-calendar`) without changing the coarse status-folder pipeline.
3. **Raw-data-layer store as the single job-postings substrate**
   (`docs/designs/raw-data-layer/execution-plan.md`): remaining work is the
   incremental O(new) build (`tasks/0_backlog/2026-07-21-store-incremental-build-o-new`)
   and the parked logs-as-projections question
   (`message-queue/needs-human/decisions/logs-as-store-projections.md`).
4. **A self-enforcing process layer** (AgentFold restructure): the reconciler is
   green in pre-commit + CI and the restructure itself is closed
   (`tasks/4_done/2026-07-22-agentfold-restructure`, PRs #56–#59; its
   top-level `handbook/` + `design/` item was later reversed by workspace phase
   2 under a superseding ADR). Remaining: queue hygiene tooling, now rewritten
   down to its two live gaps
   (`tasks/0_backlog/2026-07-21-todo-queue-hygiene-tooling`), and session
   handovers in `history/`. **The tree-instructions validator is dropped** —
   the tree it would police is 2 tracked `AGENTS.md` and 0
   `agents-references/` directories, and its own owner-decided ADR
   (`memory/decisions/tree-instruction-growth-policy.md`) holds that surface
   near zero on purpose. Its one item with a live consequence was re-filed as
   `tasks/0_backlog/2026-07-31-leak-guard-silently-skips-an-unreadable-file`.
   How much of this layer to keep at all is now an open owner decision:
   `message-queue/needs-human/decisions/process-weight-what-to-cut.md`.
5. **Benchmark and eval depth**: stage-fixtures v2, and the two remaining canary
   additions (blacklist registry rewrite, bundled-txt naming), plus the parked
   benchmark rows in the private mirror. **The v3 rejection fixture is dropped**
   — the schema is v5, the rejection logic moved out of the file the task named,
   the canary text already says "legacy v4", the behaviour is unit-tested at
   `test_progress_calendar.py`, and an invalid fixture under
   `examples/applications/` would newly break the three canaries that walk the
   example tree (`at-pipeline-health`, `at-validate-drafted-metadata`,
   `rw-duplicate-preflight`).

---

## The gap this list does not describe: the backlog is inverted relative to damage

Recorded 2026-07-31, deliberately as one paragraph here rather than as seven task
folders. Of the 24 open backlog items, 19 concern the harness that tracks the work
and 5 concern the job hunt. Meanwhile **`memory/known-issues/` holds 7 open entries
and only one is referenced by any task** — and four of those are defects in the
*product*, not the harness:

- `check-py-never-skill-hyphen-substring-false-positive` — **blocks a render with a
  spurious FAIL** on a hyphenated compound;
- `visa-sponsorship-negation-phrase-gap` — the sponsorship classifier misses real
  denial wordings, so a role that will not sponsor survives the filter;
- `location-title-only-foreign-leak` — a foreign role classifies as US-remote when
  the city appears only in the title;
- `rw-tailor-single-posting-canary-fixture-conflict` — a canary that cannot be
  satisfied against the shipped example folder.

Those four are the items with the shortest path to a wrong artifact reaching the
user, and none is on this list or in `tasks/`. **They are not converted to tasks
here on purpose**: `memory/known-issues/` is the correct container for a known
defect, and what is actually missing is a *drain* — nothing in the repo ever
promotes, expires, or re-reviews an entry, which is why one survived 49 merge cycles
against its own "delete after one PR cycle" instruction. That drain is question D7(c)
in `message-queue/needs-human/decisions/process-weight-what-to-cut.md`. Until it is
answered, treat this paragraph as the pointer the backlog does not give you.
