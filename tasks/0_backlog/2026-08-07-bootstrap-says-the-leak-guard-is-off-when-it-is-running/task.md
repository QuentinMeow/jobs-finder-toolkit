# bootstrap_overlay reports the leak guard is off when a working symlink is running it

- **Priority**: P1 (this round)
- **Area**: harness
- **Source**: Observed 2026-08-07 while wiring `bootstrap_overlay.py --check` into the new `cutover`
  validation profile. Pre-existing; unrelated to that work.
- **Claimed-by**: <(set when work starts, before the first change)>

## Goal

`bootstrap_overlay.py --check` must distinguish "the hook is not wired" from "the hook is wired by
an older mechanism we would like to migrate". Today it prints the same alarm for both, and the
alarm is false in the second case.

## Context

The overlay's hooks are currently **symlinks** into the tracked source:

```
private/.git/hooks/pre-commit -> ../../../automation/hooks/overlay-pre-commit
private/.git/hooks/pre-push   -> ../../../automation/hooks/overlay-pre-push
```

Both resolve (to `automation/hooks/overlay-pre-*`) and both are executable, so Git runs them and
**the leak guard does run on every private commit and push.** Verified:

```bash
readlink -f private/.git/hooks/pre-commit   # -> automation/hooks/overlay-pre-commit
test -x private/.git/hooks/pre-commit       # -> 0
```

`bootstrap_overlay.py --check` nonetheless exits 1 with:

> Git hook(s) NOT wired to their tracked source — the leak guard does not run on commit or push here

That sentence is factually wrong for this state. What is actually true is narrower: the hooks are
installed as symlinks rather than as the managed copies the current scheme prefers (the
`[update] … migrate managed symlink` lines say exactly that, and `pre-commit.copied-20260806`
backups show a migration in flight).

**Why this matters more than a wording nit.** It is a safety message that cries wolf. An agent or
the owner reading "the leak guard does not run" may either panic-fix by hand — the repair text
even says a foreign hook must be removed by hand — or, after seeing the false alarm once, learn to
ignore the message that would matter when a hook really is missing. It also makes the new
`cutover` profile's `overlay-bootstrap` gate red for a non-problem.

Related but distinct: [`2026-08-01-dangling-symlink-manifest-reads-as-absent`](../2026-08-01-dangling-symlink-manifest-reads-as-absent/task.md)
covers a symlink that does NOT resolve. This is the opposite case — one that does.

## Definition of done

- [ ] `--check` reports a resolving, executable symlink to the correct tracked source as a
  MIGRATION item, not as "the leak guard does not run".
- [ ] The "leak guard does not run" wording is emitted only when the hook is genuinely absent,
  dangling, non-executable, or foreign.
- [ ] A test covers all four states: managed copy, resolving symlink to the right source, dangling
  symlink, and a foreign hook.
- [ ] Exit codes still fail closed — a migration-pending state may stay non-zero, but its message
  must match what is true.
