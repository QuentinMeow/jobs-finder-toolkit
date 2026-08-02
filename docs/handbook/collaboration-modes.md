# Collaboration Modes — the human dial

One line in `AGENTS.md` declares the active mode; a task's `task.md` may
override it for that task only. The dial controls exactly one thing: **when
an agent decides alone vs. files a question vs. stops**.

| Mode | Agent decides | Agent files & proceeds | Agent stops and asks |
|------|--------------|------------------------|----------------------|
| `autonomous` | everything | FYI reviews only | never — the owner reviews if they feel like it |
| `async` (default) | everything reversible | expensive-to-reverse decisions, filed in `message-queue/needs-human/decisions/` with options + a stated default path, then continuing on the default | never for an answer — only the `AGENTS.md` Guardrails stop an agent |
| `pair` | nothing significant | — | before every meaningful step |

What counts as **expensive to reverse** (file it, don't just do it):

- deleting or rewriting owner-authored content (profile, notes, answers);
- schema/format changes that force migrating existing items;
- desired-state (roadmap) changes; new hard guardrails;
- anything the leak guard exists for — publishing surface changes;
- sending anything outside the repo (the email layer is draft-only by
  guardrail regardless of mode).

Two-way doors — code changes on a branch, queue/task/memory items, doc
edits, refactors with tests — are decided freely in `async`: git revert
makes them cheap. **Never block silently, never proceed silently**: every
fork either gets decided and noted, or filed with a default path.

`async` here means **merge-then-answer**: the owner answers a whole batch
after it lands, so a filed question never gates a merge and its default path
is what runs in `main` meanwhile. That makes the default the real deliverable
— it must be reversible, write no owner data, have no outward-facing effect,
and lose nothing silently over time. **If no default clears that bar, ship the
subset that does and say so in the item.** Never hold work for an answer:
stopping is reserved for the `AGENTS.md` Guardrails, which stop a specific
*action* (deleting owner data, sending mail, pushing over a red gate) while
the rest of the batch continues. Ranking + the `Cost if wrong` taxonomy:
`message-queue/needs-human/decisions/README.md`.
