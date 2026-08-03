# Worklog — 2026-08-03-bootstrap-repair-dangling-hooks

## 2026-08-03 — session 1 (agent)

- Filed after leak-guard setup research: local hooks were dangling post-`hooks/`→`automation/hooks/` move; bootstrap foreign-symlink policy failed open. Manual repair done on this checkout; code fix not started.

## 2026-08-03 — session 2 (agent)

- Implemented the durable fix on `fix/bootstrap-repair-dangling-hooks`. `_hook_is_repairable()`
  splits "broken install of ours" (dangling target, or a target resolving inside
  `automation/hooks/` at the wrong name) from a genuinely foreign hook; apply retargets the
  former, still never touches the latter.
- `--check` now exits 1 when any toolkit/overlay hook is not wired to its tracked source
  (missing, dangling, mis-wired, or shadowed by a foreign hook) and prints each one. Apply
  keeps exiting 0 — it repairs what it owns, and a foreign hook is a warning it cannot act on.
  Decided alone: that asymmetry, because the DoD scopes the non-zero exit to `--check` and an
  apply that exits 1 on a hook it is forbidden to clobber would break the documented setup step.
- +7 tests in `automation/hooks/tests/test_overlay_hooks.py` (26 → 33 in that suite). 6 of the 7
  fail against the pre-change `bootstrap_overlay.py`; the 7th is the guard that a foreign
  symlink resolving elsewhere is still left alone.
- Surprise, unrelated to this change: `tests-gardener` was red locally because
  `automation/maintenance/` still "existed" as untracked `__pycache__` left over from the
  031e05d rename, which `test_the_map_is_still_true_of_the_real_repo` reads off the real tree.
  Deleted the stale bytecode (untracked, generated, nothing tracked under that path); gate green.
  CI never saw it — a fresh clone has no bytecode. Nothing filed: there is no defect in the
  tracked tree, only a local artifact.
- Not done, deliberately: `bootstrap_overlay.py --check` is still in no gate table. It cannot be
  a CI gate (CI never installs hooks, so it would be red by construction there) and pre-commit
  cannot run it in a worktree. It stays a local health command, which is what the DoD asks for.
- Second red gate outside scope, this one in CI on PR #300: `pdf-tests` failed with exit 124 in
  the LibreOffice apt step, before any test ran, taking the required `build` check with it.
  `gh run rerun --failed` passed the same commit in 1m4s. Filed as
  `tasks/0_backlog/2026-08-03-libreoffice-apt-install-flakes-the-pdf-lane/` — no open item
  covered it, only a `4_done` task's verification note describing the same tail latency.
