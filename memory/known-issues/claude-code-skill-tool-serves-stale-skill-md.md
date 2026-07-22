# Claude Code `Skill` tool can serve a stale `SKILL.md` from outside the eval worktree

- **Status**: open
- **Severity**: medium (wasted cost or manual workaround)
- **Area**: harness
- **Source**: `evals/results/job-search-d81ec69b8310-20260720.md:39-42`

## Symptom

During a job-search regression eval run, the harness's built-in `Skill` tool
served a `SKILL.md` from outside the eval's isolated worktree — i.e. a stale copy
of the instruction file, not the one under test at the pinned SHA. This is a
harness-level behavior (the Claude Code `Skill` tool's resolution), not a defect
in this repository's own code.

## Reproduction

Not reliably deterministic from this repo alone (it depends on the harness's
`Skill`-tool resolution and worktree/session setup). Conditions under which it was
observed: a fresh subagent session invoked inside a detached eval worktree at a
pinned SHA, immediately after the worktree was created, using the `Skill` tool
(rather than a direct file read) to load a skill's `SKILL.md`.

## Impact

An eval runner can silently operate on the wrong instruction file, producing a
verdict for behavior that does not match the SHA under test. In the run where
this was found, later runs were constrained to read worktree files directly
(bypassing the `Skill` tool) as a workaround; the affected early runs' verdicts
were re-checked against artifacts and confirmed to still stand, but this required
manual re-verification.

## Root cause

Not fully diagnosed here — believed to be a harness-level caching/resolution
issue in the Claude Code `Skill` tool when a session starts inside a git worktree
distinct from the primary checkout, rather than anything in this repository's
`SKILL.md` files or worktree setup.

## Suggested fix

No code fix available in this repository (the defect is in the harness, not the
toolkit). Workaround, already adopted in later eval runs: inside any eval
worktree, have the runner read instruction files directly by path (e.g. `Read
skills/<skill>/SKILL.md`) instead of invoking the `Skill` tool, and note
this constraint in `evals/README.md` / the run's fixture setup so future gate
runs adopt it by default rather than rediscovering it per-run.
