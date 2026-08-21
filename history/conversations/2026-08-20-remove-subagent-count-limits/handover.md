# Handover — remove subagent count limits

- **Date**: 2026-08-20
- **Task(s)**: none

## What happened

- Nothing is blocked; public skill and agent instructions no longer impose a numeric ceiling on
  subagent use, while their remaining parallel-work guidance is unchanged.
- The obsolete central budget page and its handbook entry were removed, and the owner's pending
  decision was folded into a durable decision record.
- Focused repository checks pass. The generic skill-creator validator still rejects this repo's
  existing `visibility` frontmatter, so one backlog task records that separate incompatibility.

## Where things stand

- Public work is on `codex/remove-subagent-count-limits`; the final session reply carries the PR
  URL after push and creation.

## Decisions made for you

- Followed the owner's Option D answer: delete the fixed count everywhere it instructed agents,
  with no replacement note, exemption, or compatibility wording. Reversing this means designing
  and reintroducing a new policy.
- Added `.DS_Store` to the public ignore list instead of publishing local macOS metadata that was
  already untracked. Reversing this removes one ignore rule.
- Skipped behavior canaries because the three skill edits only delete the same prose restriction;
  no workflow, output contract, or executable path changed.

## If X then Y

- If CI reports an instruction-file issue, inspect the exact changed skill; do not restore the
  deleted limit as a compatibility fix.

## Dead ends

- The generic skill-creator validator cannot validate these repository skills because it rejects
  the repository's required `visibility` key; the repository-native checks are the authority here.

## Needs your attention

- 59 carry-over `needs-human` items remain across both repositories; none relates to this change.
  Top: [retire-copied-private-companies-root](../../../message-queue/needs-human/decisions/retire-copied-private-companies-root.md) — copied owner data may remain in the wrong tree if unresolved; doing nothing keeps the current reversible default.
