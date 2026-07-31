# docs/roadmap/ — where this repo is going vs. where it is

Two documents, one discipline:

- `desired-state.md` — what the toolkit should be, in priority order.
- `current-state.md` — what is true today, with a `Last-updated` date.

**The gap between the two is the backlog's source**: a new task in
`tasks/0_backlog/` should trace to a desired-state line; a task matching no
line means the roadmap is stale or the task is scope creep — fix whichever
is wrong. Finishing work that changes reality updates `current-state.md` in
the same change. Two things read that date, and the split is deliberate:

- the reconciler's `roadmap-dated` check **gates** on a MALFORMED roadmap — no
  `desired-state.md`, no `Last-updated` line, a line that is not an ISO date, or
  a date in the future. It runs in pre-commit and CI, so each of those blocks
  every commit until it is fixed, which takes seconds.
- the gardener's `roadmap-staleness` routine **reports** an OLD date (more than
  30 days). It is report-only and always exits 0. Age is a grooming reminder, not
  a defect in the file, and wiring it into a gate would have failed every commit
  in the repo — including a one-line fix to an unrelated script — a month after
  the last re-date.
Desired-state changes are owner-owned: file a decision in
`message-queue/needs-human/decisions/` unless the owner asked directly.
