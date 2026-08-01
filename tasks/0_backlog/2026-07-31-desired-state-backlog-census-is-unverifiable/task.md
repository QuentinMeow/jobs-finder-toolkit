# `desired-state.md`'s backlog census cannot be reproduced from the public tree

- **Priority**: P2 (someday)
- **Area**: repo
- **Source**: doc-vs-code contradiction audit, 2026-07-31 — filed as a task, not an owner
  decision: nothing here needs a ruling, only a re-measurement the public tree cannot do
- **Claimed-by**:

## Goal

The backlog census in `docs/roadmap/desired-state.md` either matches a count someone can
reproduce, or stops quoting a raw number that goes stale within a day.

## Context

`docs/roadmap/desired-state.md:58-60`:

> Recorded 2026-07-31, deliberately as one paragraph here rather than as seven task
> folders. Of the 24 open backlog items, 19 concern the harness that tracks the work
> and 5 concern the job hunt.

`ls tasks/0_backlog | wc -l` in the public tree returns **15** today. It returned **14**
when the audit measured it earlier the same day — the number moved twice within the day the
paragraph was written, which is itself the argument against quoting it.

**This is not necessarily wrong.** The private overlay has its own `tasks/0_backlog/`, so
`24` may be the correct combined total. It cannot be checked from a config-less checkout, and
it cannot be checked in CI, which never mounts the overlay. So the sentence is currently
unfalsifiable by anyone except the maintainer at a machine with the overlay mounted — and the
paragraph does not say which trees it counts, so even the maintainer cannot tell whether they
are reproducing it or re-deriving it.

**The argument the number supports probably survives.** The paragraph's point — that the
backlog is inverted relative to where the damage is, and that `memory/known-issues/` holds
seven open entries of which only one is referenced by a task — does not depend on the exact
total. The 19-versus-5 split does. Neither should be quoted again until re-run.

**Do not fold this into a `current-state.md` grooming pass.** That is a separate, larger job
(the same audit found `current-state.md` describing a repo four merges old while carrying
today's date). This task is one paragraph in the *other* roadmap file.

Requires the overlay mounted; a config-less agent can complete the second bullet below but
not the first.

## Definition of done

- [ ] The paragraph's counts are re-measured across both trees on the day it is rewritten,
      and it states which trees it counts — or
- [ ] The raw counts are replaced by the ratio and the argument they support, so the
      paragraph cannot go stale within a day of being written
- [ ] `grep -c "24 open backlog" docs/roadmap/desired-state.md` returns 0 unless 24 is the
      re-measured figure
- [ ] `.venv/bin/python automation/reconcile/reconcile.py --check` and
      `.venv/bin/python automation/gardener/verify_links.py` stay green
