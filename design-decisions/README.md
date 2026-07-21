# design-decisions/

One file per **decided** design question — a lightweight ADR log. These record
choices already made (by the owner, or by an agent within its authority) so
future sessions stop re-litigating them. Open questions that still need the
owner's input live in `unresolved-decisions/` instead, and move here once
decided.

## Rules

- Filename: `<kebab-slug>.md`.
- **Public tree ⇒ leak-guard rules apply** (no real names/employers/dated
  personal facts; personal-scope decisions go in `private/design-decisions/`).
- Never rewrite a decision file to say something different — a reversal is a
  new file that links the old one (`Superseded-by:` / `Supersedes:` headers).
- Larger design *proposals* (multi-approach explorations) stay in
  `docs/design/<topic>/`; the decision file records the outcome and links there.

## File format

```markdown
# <Title>

- **Status**: decided | superseded
- **Date**: YYYY-MM-DD
- **Decided by**: owner | agent (within standing policy)
- **Supersedes / Superseded-by**: link, if any

## Context
The problem and constraints, self-contained.

## Decision
What was chosen, stated plainly.

## Alternatives considered
Each with the one-line reason it lost.

## Consequences
What this commits us to; what would trigger revisiting.
```
