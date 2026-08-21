# Do not constrain subagent counts in repository instructions

- **Status**: decided
- **Date**: 2026-08-20
- **Decided by**: owner

## Context

The repository imposed a fixed subagent-count ceiling in its root agent contract, a handbook
page, and three public skills. The ceiling was not enforced and conflicted with explicitly long,
parallel sessions.

## Decision

Remove every subagent-count limit from skill and agent instruction files. Delete the central
budget page and do not leave replacement notes, exemptions, or backward-compatibility wording in
those instructions.

## Alternatives considered

Keeping the ceiling, narrowing it to search and application work, and adding owner-directed
exemptions all lost because each would preserve a quantity restriction or compatibility rule the
owner explicitly rejected.

## Consequences

Repository instructions no longer impose a numeric ceiling on subagent use. Task-specific user
directions and runtime capacity still determine what parallel work is possible.
