# <Problem title>

## Question at a glance

Explain the complete problem in plain English, including how later stages extend the original contract.

## Required operations

| Operation | Inputs | Returns | Required behavior |
|---|---|---|---|
| `<function>` | `<parameters>` | `<type>` | <contract and boundary rules> |

## Data model and invariants

Describe each important data structure, its shape, and the invariant it maintains.

## High-level solution

Explain what to say before coding: how data enters the system, where state lives, how operations transform it, and why the design supports every requirement.

## Example walkthroughs

### Example 1: <trusted prompt example>

Walk through each operation and show the relevant state after every step.

### Example 2: <boundary or follow-up example>

Walk through an expiration, deletion, overwrite, concurrency, or other important edge case.

## High-level pseudocode

```text
INITIALIZE:
    ...

CORE_OPERATION(...):
    ...
```

## Complexity

| Operation family | Time | Extra space | Reason |
|---|---:|---:|---|
| <family> | <complexity> | <complexity> | <why> |

## Common pitfalls

- State exact endpoint, ordering, missing-data, and overwrite rules.

## Follow-up questions

### <Likely interviewer follow-up?>

Answer directly, explain the tradeoff, and state what would change in the data model or algorithm.

## Files and recovery

- `question_description/`: curated prompt-only crops in reading order.
- `code_setup/`: useful starter scaffolds, when present.
- `originals_backup/`: checksum-verified raw captures.
- `<solution file>`: runnable solution.
