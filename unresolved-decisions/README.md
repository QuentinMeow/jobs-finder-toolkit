# unresolved-decisions/

One file per decision that **needs the owner's input**. The owner reads these
files cold — each MUST be fully self-contained: all background, the concrete
options with trade-offs, a recommendation, and what happens by default if no
answer is given. Never assume the owner has read a result file, a PR thread,
or a prior session.

## Rules

- Filename: `<kebab-slug>.md`.
- **Public tree ⇒ leak-guard rules apply**; decisions about the owner's real
  pipeline/identity go in `private/unresolved-decisions/` (same format).
- Every file states a **default path** — what agents will do (or deliberately
  not do) while the decision is pending, so pending never means stuck.
- When the owner decides: move the file to `design-decisions/` (public or
  private as appropriate), rewrite in the decided format, record the choice
  and date. Delete it from here in the same commit.
- Agents check this folder at session start for anything newly decided in
  conversation, and file new entries the moment they hit a genuinely
  owner-owned fork — instead of blocking or guessing.

## File format

```markdown
# <Title — phrased as the question>

- **Status**: awaiting-owner-input
- **Filed**: YYYY-MM-DD
- **Blocking?**: what work (if any) is blocked until decided
- **Default path**: what happens if this stays unanswered

## Background
Everything needed to decide, self-contained. Assume no other reading.

## Options
### Option A — <name>
What it means, pros, cons, cost.
### Option B — <name>
...

## Recommendation
The agent's recommendation and the one-paragraph reason.
```
