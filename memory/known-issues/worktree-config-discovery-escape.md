# Config discovery escapes nested git worktrees and resolves the parent checkout's real config.yaml

- **Status**: resolved (2026-07-29, phase 0b)
- **Severity**: medium (silent wrong-config runs in worktrees; no data loss)
- **Area**: repo
- **Source**: worktree-based agent run, 2026-07-21 (branch `fix/search-hardening`
  environment note)

## Symptom

In a worktree under `.claude/worktrees/<name>/`, running any toolkit script
WITHOUT an explicit `JOBHUNT_CONFIG` resolves the **parent checkout's real
`config.yaml`** — not the worktree's `config.example.yaml` fallback — because
config discovery walks parent directories from cwd and the worktree is
physically nested inside the main checkout.

## Reproduction

```bash
git worktree add .claude/worktrees/probe -b probe main
cd .claude/worktrees/probe
../../../.venv/bin/python -c "import sys; sys.path.insert(0, 'automation/shared'); import config; print(config._config_path())"
# → prints the MAIN checkout's config.yaml, not config.example.yaml
```

(Adjust the accessor name to whatever `automation/shared/config.py` exposes for
the resolved path; the observable is the printed path.)

## Impact

A worktree run intended to be hermetic (tests, canaries, benchmark subject
agents) silently uses the owner's real identity/paths. In the wrong
combination (e.g. a render test) that could write real-named artifacts into
a tracked tree. Every worktree agent this round had to be told to set
`JOBHUNT_CONFIG` explicitly.

## Root cause

Discovery order is `$JOBHUNT_CONFIG` → nearest `config.yaml` walking UP from
cwd → loader dir → `config.example.yaml`. The upward walk predates nested
worktrees and does not stop at a git-checkout boundary.

## Suggested fix

Stop the upward walk at the first directory containing a `.git` *file or
dir* (worktrees have a `.git` file). Inside a worktree the nearest such
boundary is the worktree root, so discovery lands on the tracked
`config.example.yaml` fallback — hermetic by default, real config only via
explicit `JOBHUNT_CONFIG`. Add a shared-suite test with a temp worktree.

## Resolution — 2026-07-29 (phase 0b)

Implemented as suggested. `automation/shared/config.py` gained `_search_up()`,
which searches each directory on the way up and stops at the first one holding
a `.git` file or directory; the boundary directory itself is searched before
the walk ends. A worktree therefore resolves to its own root and no longer
reaches the parent checkout's `config.yaml`.

One behavioural note the original writeup did not anticipate: a worktree
contains no `private/` mount (it is git-ignored and never checked out), so the
new fail-closed refusal added in the same change does **not** fire there.
A worktree run falls back to the example config and prints a one-line stderr
notice — hermetic, and no longer silent.

Pinned by `automation/shared/tests/test_config_accessors.py`, which builds a
real worktree layout (`.git` as a *file*, a parent `config.yaml` one level up)
and asserts discovery stops at the boundary.
