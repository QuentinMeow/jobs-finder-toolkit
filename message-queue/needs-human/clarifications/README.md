# message-queue/needs-human/clarifications/ — questions that matter soon

One file per question that shapes **future** work but doesn't block the
current task: the filing agent states an assumption, proceeds on it, and the
owner corrects the assumption whenever they next visit. Unlike
`../decisions/`, nothing here is a one-way door — a wrong assumption is
cheap to revert.

## File format

```markdown
# <The question, in plain words>

- **Status**: awaiting-owner-input
- **Blocking**: no (a clarification that becomes blocking is refiled as a decision)
- **Assumption**: what agents will assume until answered
- **Matters-by**: when a wrong assumption starts costing real rework
- **Filed**: YYYY-MM-DD
- **Source**: [where this came from](../../../path/to/source.md)

## Background
Enough context to answer cold, self-contained.

**Your answer:** ______
```
