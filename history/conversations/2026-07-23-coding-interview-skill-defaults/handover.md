# Handover — coding-interview skill defaults

- **Date**: 2026-07-23
- **Task(s)**: none

The private coding-interview skill now defaults to completing Python before Go when no language is selected, uses only an identifiable screenshot language, and preserves screenshot-derived code style, constraints, approach, and naming during corrections and follow-ups.

## What happened

- Added language-selection, Python-first completion, conservative dependency, screenshot-debugging, naming-preservation, and user-approach-first rules.
- Required commented historical screenshot code with `BUG:` annotations, executable corrected code with `FIX:` annotations, and a separate optimal section only when needed.
- Separated in-place bug fixes from append-only follow-up requirements, with chronological sections, distinct names, and reuse of compatible existing code.
- Required interviewer-ready high-level explanations plus concrete simulated input, step-by-step state flow, and output comments for every function and non-trivial block.
- Validated the skill with the generic validator's repository-compatible view; the real file retains its required `visibility: private` declaration.

## Where things stand

- The skill edit is complete and locally validated. The private skill is deliberately outside the public canary harness, so no coding-interview canaries exist to run.

## Needs your attention

- Nothing for this skill update.
