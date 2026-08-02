# Is "agents never delete owner data" scoped to repo-local products, or does it also bind a live Outlook event?

- **Status**: awaiting-owner-input
- **Filed**: 2026-08-02
- **Source**: [`AGENTS.md` Guardrails, "Agents never delete owner data"](../../../AGENTS.md) · [`skills/interview-calendar/SKILL.md` "Search Outlook Before Every Write"](../../../skills/interview-calendar/SKILL.md) · [contradiction audit task, item 8](../../../tasks/4_done/2026-08-01-the-contract-contradicts-itself-in-eight-places/task.md)
- **Blocks**: nothing. Both readings are live today; which one an agent follows depends on
  which surface it read first.
- **Default path**: **the stricter surface wins per object, and no contract text moves.**
  Repo-local owner data (application folders, interview prep, company dossiers, store
  payloads) is never deleted by an agent under any condition — propose in
  `message-queue/needs-human/` and stop. A live Outlook duplicate event is deleted only on
  the user's explicit approval *in that session*, never on an agent's own judgement, which
  is exactly what `interview-calendar` already requires. Nothing an agent does today
  changes while this is pending.
- **Cost if wrong**: ratify
- **Safe to merge because**: the default performs no deletion an agent could not already
  perform, and adds no permission — it is the intersection of the two surfaces, so the
  worst outcome is one extra confirmation. No file is written, so there is nothing to undo.

## Background

Two instruction surfaces disagree about whether "never delete" has an exception.

**The Guardrail is absolute.** `AGENTS.md` → Guardrails:

> **Agents never delete owner data**: application folders, interview prep, company dossiers,
> and store payloads are removed by the **user only** — never by an agent, under any
> condition, including cleanup, migration, or a rejected application. Propose a deletion in
> `message-queue/needs-human/` and stop; never perform one.

"Under any condition" plus "never perform one" admits no approved deletion at all, and the
remedy it names is repo-shaped: file a queue item.

**`interview-calendar` permits an approved one.** Its "Search Outlook Before Every Write"
step 5:

> If multiple plausible events remain, create or update nothing. Report the ambiguity. Never
> delete an existing duplicate without the user's explicit approval.

Read literally, that sentence says deletion IS available once the user approves — of a live
Outlook calendar event, which is not one of the four things the Guardrail enumerates and is
not a file in this repo at all.

The two can be reconciled by scope: the Guardrail's enumeration is repo-local owner data and
its remedy is a repo file, so a remote object the user just approved deleting arguably sits
outside it. But nothing in either file says so, and the Guardrail's heading is the broad form.
An agent that reads only `AGENTS.md` will refuse a duplicate cleanup the user explicitly
asked for; an agent that reads only the skill may generalise the approval exception back onto
application folders, which is the far more expensive mistake.

## Options

### Option A — Scope the Guardrail to repo-local owner data (recommended)

Amend the Guardrail's first clause to say it governs **owner data stored in this repo and its
overlay**, and add one clause: an action against a live third-party object (an Outlook event,
a calendar entry) follows its own skill's approval rule. `interview-calendar` is unchanged.

- What you get: both surfaces literally true; a duplicate-event cleanup you approved actually
  happens; the expensive case (application folders) keeps its absolute "under any condition".
- What it costs: one more concept in the Guardrail — "repo-local" now has to be understood,
  and a future product that stores owner data remotely needs its own sentence.

### Option B — Broaden the Guardrail; interview-calendar must route through the queue too

Delete the skill's approval clause. An agent that finds a duplicate Outlook event reports it
and files a `message-queue/needs-human/` item; the user deletes the event in Outlook.

- What you get: one rule, no exceptions, nothing to misread. Symmetric with the email
  assistant's draft-only rule (agents never take the irreversible outward action).
- What it costs: duplicate calendar events accumulate until you clear them by hand, and the
  queue collects items whose action takes you five seconds in Outlook. It also makes the
  skill's dedupe half advisory.

## Recommendation

**A.** The Guardrail's own enumeration, its remedy ("propose in `message-queue/`") and its
rationale (an agent must not destroy work that cost the owner real effort) are all repo-shaped;
a duplicate calendar event the user just asked to remove is none of those. B is defensible if
you would rather have exactly one rule than a correct one, but it makes the toolkit refuse a
tidy-up you explicitly requested, which reads as broken rather than as safe.

**Your answer:** ______
