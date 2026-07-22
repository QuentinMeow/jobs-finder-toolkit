# Process folders v2: the message-queue/ queue family

- **Status**: decided
- **Date**: 2026-07-21
- **Decided by**: owner (restructure requested explicitly while answering
  the raw-data-layer decisions; queue layout details by agent within that
  mandate)
- **Supersedes**: [process-folders-layout.md](process-folders-layout.md)

## Context

The v1 layout put four process folders at the repo root. Answering the
raw-data-layer decision set, the owner asked for a single **TODO folder
queue** as the center of AI↔human async collaboration: *"move
unresolved-decisions under TODO/ folder, so that TODO folder can contain
any arbitrary subfolders, like human decisions, review required, ai-agent-
facing task list, etc."* — one place where either side drops work for the
other, extensible with new queue types.

## Decision

- **`message-queue/` is the queue family** (things awaiting someone's action):
  `message-queue/needs-agent/requests/` (human→AI free-form drop box — new), `tasks/0_backlog/` (moved
  from root `tasks/`), `message-queue/needs-human/decisions/` (moved from root
  `unresolved-decisions/`), `message-queue/needs-human/reviews/` (optional human-eyes items —
  new). New queue types may be added as subfolders with a README, without a
  new ADR.
- **Records stay at root** (things already settled, append-only):
  `memory/decisions/`, `memory/known-issues/`.
- Private mirrors move identically: `private/message-queue/{inbox,tasks,decisions,
  reviews}/`.
- The behavioral contract (boot ritual, doc dialogue, answered-decision
  handling) lives in `AGENTS.md` → "Async Collaboration"; per-queue formats
  in each queue's README.
- No backward-compatibility aliases (owner's standing preference): all
  references updated in the same change; old paths are gone.

## Alternatives considered

- **Keep four root folders, add `inbox/` as a fifth** — rejected: the owner
  explicitly asked for one queue root, and "queue vs record" is a cleaner
  human mental model than five siblings.
- **Move `memory/known-issues/` and `memory/decisions/` under `message-queue/` too** —
  rejected: they are records nobody needs to act on; putting them in a
  folder named "todo" misstates their nature.

## Consequences

- Everything that filed into `tasks/` or `unresolved-decisions/` (eval
  follow-ups, session memory, skills) now files into `tasks/0_backlog/` /
  `message-queue/needs-human/decisions/`; `AGENTS.md` and folder READMEs updated in the same
  change.
- Historical result files' live pointers were updated; historical *prose*
  was left as written.
