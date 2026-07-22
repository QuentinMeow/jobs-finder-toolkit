# message-queue/needs-human/decisions/

One file per decision that **needs the owner's input**. The owner reads these
files cold — each MUST be fully self-contained: all background, the concrete
options with trade-offs, a recommendation, and what happens by default if no
answer is given. Never assume the owner has read a result file, a PR thread,
or a prior session.

## Rules

- Filename: `<kebab-slug>.md`.
- Every item has a **Source** link to the design, result, task, or other
  durable file that created the question. If the decision originated in
  chat, link the closest durable record and say that chat supplied the fork.
- **Public tree ⇒ leak-guard rules apply**; decisions about the owner's real
  pipeline/identity go in `private/message-queue/needs-human/decisions/` (same format).
- Every file states a **default path** — what agents will do (or deliberately
  not do) while the decision is pending, so pending never means stuck.
- When the owner decides: move the file to `memory/decisions/` (public or
  private as appropriate), rewrite in the decided format, record the choice
  and date. Delete it from here in the same commit.
- Agents check this folder at session start for anything newly decided in
  conversation, and file new entries the moment they hit a genuinely
  owner-owned fork — instead of blocking or guessing. `parked-until-revisit`
  items are skipped unless their revisit condition matches the session's
  work.
- Every file ends with a `**Your answer:** ______` line — the owner's
  expected answering surface. If a question is **mirrored from a doc's
  decision block**, folding the answer must update BOTH surfaces in the
  same commit, and on conflict **the doc block wins**.
- An answer the owner gives in chat is written into this file in the same
  turn, before any other work (chat has no file trace of its own).

## File format

```markdown
# <Title — phrased as the question>

- **Status**: awaiting-owner-input | parked-until-revisit
- **Revisit when**: (parked items only) the concrete condition that reopens this
- **Filed**: YYYY-MM-DD
- **Source**: [descriptive source](../../../path/to/source.md)
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
