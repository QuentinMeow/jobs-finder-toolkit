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
   (`docs/designs/raw-data-layer/execution-plan.md`): the incremental O(new) build
   shipped and its task is in `tasks/4_done/2026-07-21-store-incremental-build-o-new`,
   so the only thing left on this line is the parked logs-as-projections question
   (`message-queue/needs-human/decisions/logs-as-store-projections.md`) — the
   skip-logs stay the sole search/draft skip authorities until it is answered.
4. **A self-enforcing process layer** (AgentFold restructure): the reconciler is
   green in pre-commit + CI and the restructure itself is closed
   (`tasks/4_done/2026-07-22-agentfold-restructure`, PRs #56–#59; its
   top-level `handbook/` + `design/` item was later reversed by workspace phase
   2 under a superseding ADR). Remaining: queue hygiene tooling, now down to **one**
   live gap (`tasks/0_backlog/2026-07-21-todo-queue-hygiene-tooling`) — the
   company-plus-date structural screen, itself blocked on the unanswered
   `message-queue/needs-human/decisions/company-plus-date-structural-screen.md`,
   whose default path is that no screen is added. The gardener half shipped:
   `automation/gardener/gardener.py` registers `queue-hygiene` in `ROUTINES` and
   `ALL_ORDER`. Also remaining: session handovers in `history/`.
   **The tree-instructions validator is dropped** —
   the tree it would police is 2 tracked `AGENTS.md` and 0
   `agents-references/` directories, and its own owner-decided ADR
   (`memory/decisions/tree-instruction-growth-policy.md`) holds that surface
   near zero on purpose. Its one item with a live consequence was re-filed and is
   now done (`tasks/4_done/2026-07-31-leak-guard-silently-skips-an-unreadable-file`;
   the one path it was told not to change is open as
   `tasks/0_backlog/2026-07-31-leak-guard-cannot-read-non-utf8-text`).
   How much of this layer to keep at all is now an open owner decision:
   `message-queue/needs-human/decisions/process-weight-what-to-cut.md`.
5. **Benchmark and eval depth**: stage-fixtures v2, and the two remaining canary
   additions (blacklist registry rewrite, bundled-txt naming), plus the parked
   benchmark rows in the private mirror. **The v3 rejection fixture is dropped**
   — the schema is v5, the rejection logic moved out of the file the task named,
   the canary text already says "legacy v4", the behaviour is unit-tested at
   `test_progress_calendar.py`, and an invalid fixture under
   `examples/me/applications/` would newly break the three canaries that walk the
   example tree (`at-pipeline-health`, `at-validate-drafted-metadata`,
   `rw-duplicate-preflight`).

---

## The gap this list does not describe: the backlog is inverted relative to damage

Recorded 2026-07-31, re-derived 2026-08-02, deliberately as one paragraph here rather
than as seven task folders.

**The census is a command, not a number.** The original hand count (24 open items, 19
harness / 5 job hunt) could not be re-derived from any tree, and the public count alone
moved 15 → 18 → 38 → 62 → 60 in the four days around it — the last two figures inside one
session, because closing a task changes the number. So run it instead of reading it:

```bash
ls tasks/0_backlog | wc -l                                              # open items
grep -rh '^- \*\*Area\*\*:' tasks/0_backlog/*/task.md | sort | uniq -c | sort -rn
```

The second line splits the backlog on the `- **Area**:` field that `templates/task/task.md`
already requires of every task — a mechanical stand-in for the "harness vs job hunt"
judgement the original paragraph made by hand. With the overlay mounted, run both against
`private/tasks/0_backlog/` too and add the totals. **Print counts only**: a private task's
id, slug or title must never reach this file or a public commit message.

The claim this section rests on is the SHAPE, not the figure, and the shape has held at
every measurement: the backlog is dominated by the harness that tracks the work, while the
defects with the shortest path to a wrong artifact reaching the user sit in
`memory/known-issues/` and on no list at all. **No figure is quoted here on purpose.** The
last one written into this paragraph was already wrong the day it was written and was wrong
again a day later, for the reason stated above — closing a task changes the number, and this
page is not re-derived on every merge. Run the two commands; the answer they print is the
record. The split to read off the second command is `harness + repo + benchmarks` (the
harness that tracks the work) against `job-search + resume-writer + email + tracker` (the
product a user touches); the first side has been the larger one at every measurement, and
the `Area` field draws the line more mildly than the original hand count's prose did.

Meanwhile **`memory/known-issues/` holds 4 open entries** (down from 7 on 2026-07-31; three
were closed on 2026-08-02 after being verified fixed in code, and each names its fixing
commit). Two of the four remaining are defects in the *product*, not the harness:

- `check-py-never-skill-hyphen-substring-false-positive` — **blocks a render with a
  spurious FAIL** on a hyphenated compound;
- `visa-sponsorship-negation-phrase-gap` — the sponsorship classifier misses real
  denial wordings, so a role that will not sponsor survives the filter.

Two more that this list carried are now closed and must not be re-opened from here:
`location-title-only-foreign-leak` was fixed by `e967b91` (the search leg passes the title
to the classifier, which reads it in the rejecting direction), and
`rw-tailor-single-posting-canary-fixture-conflict` by `1a1fbac` (the canary got its own
isolated fresh-tailoring scaffold). Each entry carries its Resolution.

Those two are the items with the shortest path to a wrong artifact reaching the
user, and neither is on this list or in `tasks/`. **They are not converted to tasks
here on purpose**: `memory/known-issues/` is the correct container for a known
defect, and what is actually missing is a *drain* — nothing in the repo ever
promotes, expires, or re-reviews an entry, which is why one survived 49 merge cycles
against its own "delete after one PR cycle" instruction. (The three closed on 2026-08-02
were drained by a session doing it by hand, which is evidence for the gap, not against it:
all three had been fixed in code for a week or more and nothing noticed.) That drain is question D7(c)
in `message-queue/needs-human/decisions/process-weight-what-to-cut.md`. Until it is
answered, treat this paragraph as the pointer the backlog does not give you.
