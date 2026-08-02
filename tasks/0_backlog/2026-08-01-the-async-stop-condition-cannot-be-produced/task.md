# The `async` mode's stop condition cannot be produced by the schema agents must copy

- **Priority**: P1 (this round)
- **Area**: repo
- **Source**: instruction-conflict audit, 2026-08-01
- **Claimed-by**:

## Goal

The one condition that makes an agent STOP in `async` mode is expressible in the file format agents
are required to use, and at least one live decision item can actually trigger it.

## Context

`AGENTS.md:17-19` sets the stop condition as a literal sentinel:

> **Collaboration mode:** `async` — decide everything reversible; file expensive-to-reverse choices
> in `message-queue/needs-human/decisions/` with a default path and continue; stop only on
> `Blocking: yes`.

`docs/handbook/collaboration-modes.md:10` mirrors it verbatim: "only when a decision file says
`Blocking: yes`".

The schema those files are made from cannot say that. `templates/queue/decision.md:6` is

```
- **Blocking**: <what work (if any) is blocked until decided; "nothing" otherwise>
```

— a prose field whose stated null value is `nothing`, not a boolean. All 26 live items follow it:
25 read `- **Blocking**: nothing…`, and the one genuinely blocking item,
`message-queue/needs-human/decisions/examples-reshape-seven-calls.md:6`, reads

```
- **Blocking**: the `examples/` half of workspace phase 8. Its instruction-surface half is …
```

An agent applying the contract literally scans past exactly the item the rule exists to catch, and
`Blocking: yes` has never appeared in the repo.

The two queue templates also disagree with each other: `templates/queue/clarification.md:4` is
`- **Blocking**: no` — the boolean form — while the decision template is prose.

**Which side is right.** The template, on the contract's own rule: `AGENTS.md:193-194` says "Copy
its schema from `templates/` — never write a format from memory", and prose carries *what* is
blocked, which is the information a reader needs. So the cheap fix is to restate the stop condition
in both docs as "stop when a decision file's `Blocking` names real work — i.e. anything other than
`nothing`/`no`", and to align the clarification template's null value with the decision template's.
The expensive alternative (make `Blocking` a boolean and migrate 26 files plus a second field for
the prose) is not recommended, but it is the reason this is filed rather than silently edited: it
changes a schema, which `docs/handbook/collaboration-modes.md:16` classes as expensive to reverse.

`automation/reconcile/reconcile.py` does not validate the value of any `Blocking` field
(`check_queue_schema` requires only the KEYS `Status` and `Filed` for decisions), so nothing gates
either direction today.

## Definition of done

- [ ] `AGENTS.md` and `docs/handbook/collaboration-modes.md` state one stop condition, in words the
      decision template can produce, and they match each other.
- [ ] `templates/queue/decision.md` and `templates/queue/clarification.md` agree on the null value.
- [ ] `grep -rn 'Blocking: yes' AGENTS.md docs/ templates/ message-queue/` returns nothing, or
      returns a sentinel that a live file actually uses.
- [ ] `.venv/bin/python automation/reconcile/reconcile.py --check --require-roots` clean.

## 2026-08-01 — superseded in place by PR #188

PR #188 (`docs/05-queue-merge-then-answer`) shipped the opposite fix from the one this task
recommends. Instead of restoring a producible stop condition, it removes queue-level stop
authority entirely: `Blocking:` is renamed to `Blocks:`, a pure-prose field that never stops an
agent (its value was always going to be "nothing" or a description, never a boolean sentinel),
and the sole stop authority is now the `AGENTS.md` Guardrails, which halt one specific action
(deleting owner data, sending mail, pushing over a red gate) rather than a whole batch.

This task is marked **superseded in place** — not deleted, and no text above this note has been
changed. Its audit of why the old `Blocking: yes` sentinel could never fire stands as the record
of the problem; PR #188 just answers it differently than recommended here. The owner may still
reverse this via
`message-queue/needs-human/decisions/blocks-rename-supersedes-the-stop-condition-task.md`
(status: awaiting-owner-input as of this note) — if answered Option B or C there, this task's
fix ships after all.
