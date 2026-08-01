# The export destination guard refuses every path under a git checkout, with no override

- **Priority**: P1 (this round)
- **Area**: harness
- **Source**: disclosed by the exporter-guard stack's landing plan; no PR in that
  stack fixes it. Re-confirmed while fixing the location residency regression
  (branch `fix/45-us-remote-residency`).
- **Claimed-by**:

## Goal

Stop the destination guard from refusing a legitimate export destination merely
because SOME ancestor directory — possibly `~` or `~/code` — happens to be a git
checkout, without turning the guard off.

## Context

`automation/publish/export_public.py::destination_refusal` ends with:

```python
enclosing = _enclosing_git_repo(dest)
if enclosing is not None:
    return f"it is inside another git checkout ({enclosing})"
```

and `_enclosing_git_repo` walks `dest.parents` all the way to `/`, returning the
first ancestor holding a `.git` entry. The refusal is unconditional: there is no
flag that overrides it (`--force` governs only `overwrite_refusal`, a different
allowlist, and `--strict` only escalates warnings).

The rule is right in intent — an export dropped inside somebody else's working
tree shows up as untracked files in their `git status` and can be committed by
accident. It is the SCOPE that is wrong. Anyone who keeps their home directory or
their `~/code` under version control — dotfile repos make this ordinary — has
every path beneath it refused, including `~/code/jobs-finder-public`, which is the
destination the workflow is actually for. The user is left with no in-tool answer
other than moving the destination outside the tracked tree entirely.

Two shapes worth weighing when this is picked up (the choice is an owner call, so
file it as a decision if it is not obvious at the time):

- **Bound the walk.** Stop at the nearest checkout and refuse only when `dest`
  would land INSIDE that checkout's tracked area — or stop the walk at `$HOME`, on
  the argument that a home-directory dotfile repo is not "somebody's working tree"
  in the sense the guard means.
- **Add an explicit override flag** (`--allow-enclosing-repo`), so the refusal
  stays the default and the user states the exception once. This keeps the guard
  fail-closed, which is the property the whole module is built around.

Whichever is chosen, the refusal message should name the override, because today
it names a problem with no stated remedy.

Not fixed on the branch that found it: that branch is a location-classifier fix,
and this changes a safety guard that stands between the exporter and the owner's
data — it needs its own review and its own destination tests.

## Definition of done

- A destination under an enclosing git checkout is either accepted under the
  chosen scoping rule or accepted behind an explicit flag; the default behaviour
  for an unflagged, genuinely-inside-someone's-tree destination is still a refusal.
- The refusal message names the remedy.
- New cases in `automation/publish/tests/test_export_destination.py` cover: a
  destination under a git checkout with no flag (refused), the same with the
  override (accepted), and a destination inside the SOURCE checkout (still refused
  by its own earlier rule, unaffected by the override).
- `python -m unittest discover automation/publish/tests` passes.
