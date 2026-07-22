# Config discovery escapes nested git worktrees and resolves the parent checkout's real config.yaml

- **Status**: open
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
