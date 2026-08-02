# Fall back to the example persona only when no private overlay is mounted

- **Status**: decided
- **Date**: 2026-07-29
- **Decided by**: owner — answered "option A" on the queue item
  `message-queue/needs-human/decisions/config-discovery-example-fallback.md`, which this
  file replaces
- **Supersedes / Superseded-by**: narrows item 0.3 of
  [the workspace-restructure execution plan](../../docs/designs/workspace-restructure/execution-plan.md#merged-phase-0--the-gates-fail-closed),
  which said to make discovery raise unconditionally

## Context

`automation/shared/config.py` resolves the active config in three steps: `$JOBHUNT_CONFIG`
(only when the path exists) → the nearest `config.yaml` walking up from the working directory
and then from the loader's own directory → the tracked `config.example.yaml`. The last step
used to return unconditionally, so a maintainer who ran a tool from the wrong directory
silently operated on the fictional "Jordan Rivers" persona while their real data sat on disk
one directory away. A malformed (rather than missing) `config.yaml` degraded the same way,
into every hardcoded default, with no signal at all. A filed instance of the same family was
the worktree config-discovery escape, where the upward walk escaped a git worktree and
resolved the parent checkout's config (its known-issue entry was closed as fixed and deleted
in `8e4816f`; git history is the archive).

The execution plan asked for an unconditional raise. That is stricter than it sounds, because
the example fallback is a **documented public feature**: `README.md` and
`docs/handbook/architecture.md` both promise that a fresh clone of the public toolkit runs out
of the box against the example data, so an unconditional raise turns every first-run command in
the quickstart into an error.

## Decision

**Option A — raise only in a maintainer checkout.** Concretely, four behaviours:

- Fall back to `config.example.yaml` when discovery finds nothing **and** no `private/` overlay
  is mounted, printing a one-line notice to stderr so the fallback is never silent.
- Raise `ConfigNotFound` when an overlay **is** mounted and no real `config.yaml` was found —
  that combination means real data is present and the tool is about to operate on the fictional
  persona.
- Stop the upward walk at the first `.git` boundary either way, which closes the worktree
  escape.
- `JOBHUNT_REQUIRE_REAL_CONFIG=1` forces the raise everywhere, including a fresh public clone.

A malformed `config.yaml` raises under every option, and does here: silently degrading a YAML
syntax error into every hardcoded default has no defensible reading.

**Nothing changed at decision time.** This was the default path the queue item ran on while it
waited for an answer, and it was already implemented in phase 0b —
`REQUIRE_REAL_CONFIG_ENV_VAR` (`automation/shared/config.py:104`), `ConfigNotFound` (`:178`),
`_refuse_example_fallback()` (`:209`), the raise (`:247`) and `overlay_mounted()` (`:504`),
mirrored byte-identically into the four vendored copies and covered by
`automation/shared/tests/test_config_accessors.py`. The decision is a record-and-close: it
converts a live default into a settled position so no later session re-opens it.

## Alternatives considered

- **Option B — raise whenever no real `config.yaml` is found.** What the execution plan
  literally said, and the clean version with no proxy signal. Lost because it costs the
  out-of-the-box property the public repo advertises: the quickstart would need
  `JOBHUNT_CONFIG=config.example.yaml` exported first, and two published docs would need
  rewriting to match.
- **Option C — never raise; only make the fallback loud.** Lost because a stderr notice is
  exactly what a long scripted run buries, and the phase this came from exists to remove checks
  that report success while inspecting the wrong thing.

## Consequences

- The public quickstart keeps working unchanged; no doc rewrite is owed.
- **The residual the chosen option itself admits: `private/` being mounted is a proxy for
  intent, not a statement of it.** A maintainer who temporarily deletes or unmounts their
  overlay falls back to the example persona silently again — the stderr notice still fires, but
  the raise does not. This is narrow and accepted, not overlooked. `JOBHUNT_REQUIRE_REAL_CONFIG=1`
  is the escape hatch for anyone who wants the strict rule without waiting for a re-decision.
- Switching to Option B later stays a one-function change (`_refuse_example_fallback`) plus the
  two doc edits it names, so this is cheap to revisit.
- **Revisit if** the proxy is observed failing in practice — a maintainer operating on example
  data without noticing — or if the public quickstart stops depending on a zero-config first
  run, which would remove Option B's only real cost.
