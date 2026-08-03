# Run the canaries this nine-rung defect stack owes

- **Priority**: P1 (this round)
- **Area**: harness
- **Source**: the 2026-08-02 defect stack (`fix/vendor-reverse-audit` …
  `chore/records-match-the-tree`); this is the `Eval gate: debt` item its tip names
- **Claimed-by**: <(set when work starts, before the first change)>

## Goal

Run the canary sets the stack's instruction-file edits put in the MUST/MAY bands, and
record the results under `evals/results/`, so the stack's deferred eval-gate obligation is
discharged with a measurement rather than a promise.

## Context

Three rungs of the stack touch skill instruction files, and one rung changes a classifier
verdict without touching one. The obligation is deferred to the tip
(`chore/records-match-the-tree`) under gate 11's `stack` form, and the tip discharges it as
tracked debt because a canary run is a live agent run against real job boards — it cannot
be produced inside the PR that owes it.

What is owed, and why each one:

1. **`evals/canaries/job-search.yaml`** — two separate reasons, and they need one run
   between them.
   - `docs/job-search-location-routing` rewrote where the four search-time location keys
     come from (the active search profile's `location:` block, not
     `config.location_policy()`) across `SKILL.md`, `reference.md`,
     `profiles/README.md`, `_TEMPLATE.yaml` and the module docstring — **and corrected the
     canary that had been grading an agent as correct for repeating the false claim.** A
     canary whose expected answer changed has not been run against its new answer.
   - `fix/visa-classifier` changed what `classify_sponsorship()` returns on three
     sentence shapes. `js-visa-require-positive` is the canary whose whole subject is the
     policy affected. The number that matters is not in any unit test: **how often the
     recall trade lands on real postings.** Under `--visa-policy require_positive` some
     rows that used to read as explicit offers now read `review`, and only a live run
     says whether that is a handful or a flood.
2. **`evals/canaries/resume-writer.yaml`** — `docs/resume-writer-gate-truth` corrected four
   documented thresholds to match `check.py`. That rung discharged gate 11 with a written
   `skipped` rationale (MAY-skip band: correcting numbers and one warning string to match
   code reality), which is legitimate on its own. It is named here because a gated run at
   head covers it for free, not because the skip was insufficient.
3. **`evals/canaries/github-workflow.yaml`**, if a set exists — `chore/records-match-the-tree`
   edits `skills/github-workflow/SKILL.md`, which is what binds the tip to gate 11 at all.
   Its edit is a two-line re-point of paths that moved. If no canary set exists for this
   skill, record that as the finding and skip it — a skill with no set skips with a
   recorded rationale, per `evals/README.md`.

Run at a **merged** commit on `main`, not at a branch tip: an intermediate measurement is
stale the moment the rung above it lands, which is the whole reason the obligation moved to
the tip in the first place.

Related open items, deliberately not folded in — check each before starting, since a
single run may close more than one:
`tasks/0_backlog/2026-08-01-re-run-job-search-canaries-at-a-merged-commit`,
`tasks/0_backlog/2026-08-02-audit-stacks-whose-tip-never-ran-canaries`, and PR #214's
`tasks/0_backlog/2026-08-02-run-job-search-canaries-after-unreachable-negation` — that last
one arrives only if #214 is reopened, since #214 is closed as superseded by
`fix/visa-classifier`.

## Definition of done

- A record under `evals/results/` naming the merge commit the run was made at, the
  model it was pinned to, and the canary ids that ran.
- The job-search record answers the one question no unit test can: on a live sweep, what
  share of postings that previously graded an explicit sponsorship offer now grade
  `review`. A number, with the sweep size beside it.
- No large efficiency regression against the previous recorded run, per `evals/README.md`.
- Any canary set found not to exist is named in the record as a skip with its rationale,
  rather than silently omitted.
