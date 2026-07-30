# Should config discovery still fall back to the example persona in a maintainer checkout?

- **Status**: awaiting-owner-input
- **Filed**: 2026-07-28
- **Source**: [execution plan, item 0.3](../../../docs/designs/workspace-restructure/execution-plan.md)
- **Blocking**: nothing — implemented on the default path below.
- **Default path**: raise **only** when a `private/` overlay is mounted and no real
  `config.yaml` was found; a fresh public clone keeps its silent example fallback (now with a
  one-line stderr notice). `JOBHUNT_REQUIRE_REAL_CONFIG=1` forces the raise everywhere.
- **Implemented**: 2026-07-29 (phase 0b) — the default path is live in
  `automation/shared/config.py` (`ConfigNotFound` / `ConfigError`, `_search_up()`'s `.git`
  boundary) plus the four vendored copies, covered by
  `automation/shared/tests/test_config_accessors.py`. Switching to Option B later is a
  one-function change (`_refuse_example_fallback`) plus the two doc edits it names.

## Background

`automation/shared/config.py:_find_config_path()` resolves the active config in three steps:
`$JOBHUNT_CONFIG` (only if the path exists) → the nearest `config.yaml` walking up from `cwd`
and then from the module's own directory → the tracked `config.example.yaml`. The last step
returns unconditionally, without an existence check, and `_load()` swallows both `OSError` and
`yaml.YAMLError` into `{}`. So a maintainer running any tool from the wrong directory silently
operates on the fictional "Jordan Rivers" persona instead of their real data, and a malformed
`config.yaml` degrades to every hardcoded default with no signal at all.

There is a filed instance of this already:
`memory/known-issues/worktree-config-discovery-escape.md` — the upward walk escapes a git
worktree and resolves the *parent* checkout's config.

The execution plan's item 0.3 says to make this **raise** and keep the example reachable only
through an explicit `JOBHUNT_CONFIG`. That is stricter than it first looks, because the
example fallback is a **documented public feature**: `README.md` and `docs/handbook/architecture.md`
both promise that a fresh clone of the public toolkit runs out of the box against the example
data. Removing it turns every first-run command in the quickstart into an error.

Measured against the current tree, an unconditional raise is safe for the test suite — the
leak-guard tests scan synthetic fixture trees and never depend on discovery, and every skill
test either sets `$JOBHUNT_CONFIG` or writes a real temp `config.yaml`. The cost is entirely
borne by new users. *(2026-07-29 correction: an earlier draft of this paragraph credited the
leak guard's "arming" tests, which belong to phase 0a and are not in this branch. The
conclusion is unchanged — verified by running all seven suites after the change.)*

## Options

### Option A — Raise only in a maintainer checkout (default path)

Fall back to the example when discovery finds nothing **and** no `private/` overlay is
mounted, printing a one-line notice to stderr so the fallback is never silent. Raise when
`private/` **is** mounted and no real `config.yaml` was found, because that combination means
real data is present and the tool is about to operate on the fictional persona. Stop the
upward walk at the first `.git` boundary either way, which closes the worktree escape.
`JOBHUNT_REQUIRE_REAL_CONFIG=1` forces the raise unconditionally.

Keeps the quickstart working. The signal (`private/` exists) is a proxy rather than a
statement of intent, so a maintainer who deletes their overlay temporarily would fall back
silently again — narrow, and the stderr notice still fires.

### Option B — Raise whenever no real `config.yaml` is found

What item 0.3 literally says. Simplest rule, no proxy signal, nothing to explain. Costs the
out-of-box property: the public quickstart would need `JOBHUNT_CONFIG=config.example.yaml`
exported first, and `README.md` plus `docs/handbook/architecture.md` would need rewriting to match.

### Option C — Never raise; only make the fallback loud

Print the notice, fix the `.git` boundary, leave the fallback in place everywhere. Zero
breakage, but a notice on stderr is exactly the kind of thing a long scripted run buries — and
the whole point of phase 0 is that a check which reports success while inspecting the wrong
thing is worse than no check.

## Recommendation

**Option A.** The hazard is specific — real data on disk, tool silently pointed at the
fictional one — and the `private/` mount is a reliable marker of exactly that situation. It
closes the case that matters without breaking the property the public repo advertises. If you
would rather not carry the proxy, Option B is the clean version and I will rewrite the two docs
to match.

Note that regardless of which you pick, a malformed (as opposed to missing) `config.yaml` will
raise: silently degrading a YAML syntax error into every hardcoded default has no defensible
reading.

**Your answer:** ______
