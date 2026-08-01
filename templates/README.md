# templates/ — the single source of truth for file schemas

To create any queue item, task file, memory entry, or handover: **copy the
template and fill the blanks** — never write the format from memory, and
never restate a field list in another doc (link here instead; a README may
summarize *rules*, but the schema lives in the template).

| Template | Creates |
|----------|---------|
| `templates/queue/decision.md` | `message-queue/needs-human/decisions/<slug>.md` |
| `templates/queue/clarification.md` | `message-queue/needs-human/clarifications/<slug>.md` |
| `templates/queue/review.md` | `message-queue/needs-human/reviews/<slug>.md` |
| `templates/queue/retry.md` | `message-queue/needs-agent/retries/<check>--<slug>.md` |
| `templates/task/task.md` | `tasks/<status>/<YYYY-MM-DD-slug>/task.md` |
| `templates/task/worklog.md` | `tasks/<status>/<id>/worklog.md` |
| `templates/task/verification.md` | `tasks/<status>/<id>/verification.md` |
| `templates/memory/decision.md` | `memory/decisions/<slug>.md` (ADR) |
| `templates/memory/known-issue.md` | `memory/known-issues/<slug>.md` |
| `templates/memory/fact.md` | `memory/facts/<slug>.md` |
| `templates/memory/lesson.md` | `memory/lessons/<area>/<slug>.md` |
| `templates/handover.md` | `history/conversations/<YYYY-MM-DD>-<slug>/handover.md` |

Conventions: placeholders look like `<this>`; every `- **Key**: ` line is
required unless marked `(optional)`. `needs-agent/requests/` has no template
— it is deliberately format-free.

**To change a format**: change the template AND the matching check in
`automation/reconcile/reconcile.py` in the same commit, and migrate every
existing item. The reconciler validates real files against these required
keys and skips this folder itself.
