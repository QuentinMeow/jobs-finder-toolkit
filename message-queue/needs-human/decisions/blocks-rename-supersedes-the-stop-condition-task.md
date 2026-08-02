# Does the `Blocks:` rename supersede the open stop-condition task, or does that task still ship?

- **Status**: awaiting-owner-input
- **Filed**: 2026-08-01
- **Source**: [task: the async stop condition cannot be produced](../../../tasks/0_backlog/2026-08-01-the-async-stop-condition-cannot-be-produced/task.md)
- **Blocks**: nothing today, but the two changes must not ship independently — they move
  the same rule in opposite directions.
- **Default path**: **ship the rename; treat the task as superseded.** No agent starts the
  task's fix. The task is **not deleted** — it is marked superseded in place, with a
  pointer to this item, by whoever next owns `tasks/`.
- **Cost if wrong**: one-time
- **Safe to merge because**: the rename is a text change across the queue schema and its
  three contract docs — `git revert` restores the old wording, and no item's content is
  lost because `Blocks:` carries exactly the prose `Blocking:` carried. The task file
  itself is untouched by this PR.

## Background

Task `2026-08-01-the-async-stop-condition-cannot-be-produced` (P1, backlog) found that
`AGENTS.md`'s one stop condition — *"stop only on `Blocking: yes`"* — cannot be produced by
the schema agents are required to copy. The decision template's field is prose whose stated
null value is `nothing`, and `Blocking: yes` has never appeared in the repo. Its
recommended fix is to **restore a producible stop condition**: restate the rule as "stop
when `Blocking` names real work", and align the two queue templates' null values.

This PR takes the opposite route. It removes stop authority from the queue entirely:
`Blocking:` becomes `Blocks:`, explicitly prose that never stops anyone, and the only stop
authority is the Guardrails list in `AGENTS.md`.

**Why this PR went the other way.** You answer after a whole batch merges, not between
sessions. A queue item that stops an agent would therefore stop it for weeks — and the
last batch was 48 stacked PRs against 26 open decisions. A producible stop condition would
have worked exactly once per batch and then held everything. The Guardrails already stop
the *action* (deleting owner data, sending mail, pushing over a red gate) while the rest of
the batch continues, which is the behaviour that has actually held up under batch
conditions.

**Where the two agree.** Both say the current text is broken and both say the templates
must agree on a null value. This PR satisfies that half of the task's definition of done:
`templates/queue/decision.md` and `templates/queue/clarification.md` now use the same
`Blocks:` prose field, and `grep -rn 'Blocking: yes' AGENTS.md docs/ templates/
message-queue/` no longer returns a rule that nothing can satisfy.

**What is left unsatisfied** is the task's premise — that `async` should have a stop
condition at all.

## Options

### Option A — rename ships, task superseded (the default path)

Mark the task superseded in place, pointing at this item and at the guardrail bullet that
replaced the stop semantic.

- One rule, in one place, that matches how you actually work.
- The task's audit is preserved as the record of why the old rule was dead.
- Cost: `async` has no queue-level stop at all. If you ever want a question to genuinely
  hold a batch, there is no field for it — you would file it as a guardrail instead.

### Option B — task ships too, restoring a producible stop condition

Keep `Blocks:` as prose but add a separate boolean that agents honour.

- Preserves an escape hatch for a question that truly must not ship unanswered.
- Cost: reintroduces the thing that just failed. Under merge-then-answer the hatch stops
  work until the *next* batch — and the field would be set by the agent that filed the
  question, which is the party least able to judge whether your whole batch should wait.

### Option C — neither; revert both and leave the contract as-is

- Cost: leaves a documented stop condition that provably cannot be produced. This is the
  status quo the task was filed against.

## Recommendation

**Option A.** The stop condition was dead on arrival and its death caused no observed harm
across 48 PRs, while three Guardrails demonstrably stopped actions and shipped the rest.
Restoring a producible version would make the contract self-consistent in the wrong
direction — consistent with a workflow where you answer between sessions, which is not the
one you use. If a genuine must-not-ship-unanswered case ever appears, a Guardrail is the
right home for it: guardrails stop an action, not a batch.

Note: this PR deliberately does not edit the task file — `tasks/` is being changed
concurrently by other work.

**Your answer:** ______
