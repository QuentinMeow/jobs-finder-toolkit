# docs/roadmap/ — where this repo is going vs. where it is

Two documents, one discipline:

- `desired-state.md` — what the toolkit should be, in priority order.
- `current-state.md` — what is true today, with a `Last-updated` date.

**The gap between the two is the backlog's source**: a new task in
`tasks/0_backlog/` should trace to a desired-state line; a task matching no
line means the roadmap is stale or the task is scope creep — fix whichever
is wrong. Finishing work that changes reality updates `current-state.md` in
the same change. The reconciler's `roadmap-fresh` check reads that date: it
fails when the line is missing, unparseable, in the future, or more than 30
days old — and it runs in pre-commit and CI, so a roadmap nobody has re-dated
for a month blocks commits until somebody does.
Desired-state changes are owner-owned: file a decision in
`message-queue/needs-human/decisions/` unless the owner asked directly.
