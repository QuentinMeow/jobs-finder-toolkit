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
- **Nothing here ever stops an agent.** Questions ship merged and unanswered;
  the owner answers in batch afterwards. The stop authority is the Guardrails
  list in `AGENTS.md`, which stops the *action* (deleting owner data, sending
  mail, pushing over a red gate) and never the batch.
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

## The default path is what actually runs

An answer arrives *after* the batch merges, so a pending item's default path is
the behaviour that runs in `main` for weeks. It is load-bearing, not a
placeholder. A default path is **mergeable** only if all four hold:

1. **reversible** — a revert or a named command undoes it;
2. **writes no owner data** — no application folder, log row, profile, or
   mailbox state;
3. **no outward-facing effect** — nothing leaves the repo;
4. **no compounding silent loss** — it does not lose a little more each run.

**When no default satisfies all four, ship less** — descope to the part that
does, and say in the item what was left out. Never hold the batch for an answer.

`Cost if wrong` classes the queue by what a wrong default costs. **Worst first:**

| Value | Meaning |
|-------|---------|
| `recurring-loss` | fails test 4 — every run loses a little more, silently (missed postings, dropped matches). Answer these first. |
| `data` | fails test 2 — the default writes owner data; undo is a manual, per-row owner command. |
| `one-time` | a bounded cost paid once when the answer lands (a backfill, a re-run). |
| `ratify` | the default IS the shipped behaviour; answering only blesses it. Cheapest to leave open. |

There is no index file. This is the list, and it cannot go stale:

```bash
grep -H '^- \*\*Cost if wrong\*\*' message-queue/needs-human/decisions/*.md | sort -k2
```

It groups the open items by class (alphabetically — read them in the table's order above,
not the shell's). Add `recurring-loss` or `data` to the pattern to see only the two that
actually cost something.

## Answering in batch

The owner answers post-merge in `message-queue/ANSWERS.md`, one `## <slug>`
block per item. Folding a pass of answers takes **one** `Status: folding`
commit for the whole pass, not one per item; then fold, record, and delete the
answered items together.

## File format

Copy `templates/queue/decision.md` and fill the blanks — the template is
the single source of truth for this schema (validated by
`automation/reconcile/reconcile.py`).
