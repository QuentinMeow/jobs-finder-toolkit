# Bootstrap should repair dangling toolkit hook symlinks

- **Priority**: P1
- **Area**: harness
- **Source**: 2026-08-03 incident — local leak guard never ran because `.git/hooks/{pre-commit,pre-push}` still pointed at deleted `hooks/` after the move to `automation/hooks/` (commit `dd4daa6`); bootstrap warned "foreign symlink" and left them. Git skipped the non-executable hooks. CI caught the leak; local did not.
- **Claimed-by**: agent (2026-08-03, branch `fix/bootstrap-repair-dangling-hooks`)

## Goal

Make `automation/bootstrap_overlay.py` detect and retarget (or fail `--check` on) toolkit hook symlinks that do not resolve to the tracked `automation/hooks/*` scripts, so a stale install cannot silently disable pre-commit / pre-push leak guards.

## Context

- Install path: `automation/bootstrap_overlay.py` → `_install_hooks` with `allow_replace_symlink=False` for toolkit hooks (never clobber a "foreign" hook).
- After `hooks/` → `automation/hooks/`, existing local symlinks `../../hooks/pre-commit` became dangling. Bootstrap treated them as foreign, printed WARN, exited 0.
- Git does not run a hook whose symlink target is missing / not executable — commit and push succeed with no leak-guard output.
- Intended contract: pre-commit runs `check_public.py --staged --allow-unarmed`; pre-push runs the armed whole-tree guard on public remotes (`docs/handbook/private-overlay.md`, `automation/hooks/pre-{commit,push}`).
- This workstation was manually repaired to `../../automation/hooks/pre-{commit,push}`; the durable fix is in bootstrap (and optionally a health check).
- Investigation notes from the session that found this: treat dangling targets under the retired `hooks/` prefix (or any non-resolving toolkit hook link) as **repairable**, not foreign. Keep true third-party hooks (real foreign scripts) untouched.

## Definition of done

- [x] Bootstrap **apply** retargets dangling / retired-path toolkit hook symlinks to `automation/hooks/pre-commit` and `pre-push`.
- [x] Bootstrap **`--check`** exits non-zero when toolkit hooks are missing, dangling, or point elsewhere than the tracked sources (so CI/local health catches a broken install).
- [x] A unit or gate test covers: dangling `../../hooks/pre-commit` → repaired (apply) / failed (`--check`).
- [x] True foreign hooks (e.g. a real file or unrelated symlink not under the retired path) remain WARN-and-leave, documented in the bootstrap docstring.
- [x] `python automation/bootstrap_overlay.py --check` is green on a fresh install after the change.

## Decided without asking

- **`--check` fails, apply does not.** A foreign hook still means the leak guard does not run, so
  `--check` counts it as unwired and exits 1. An apply run keeps exiting 0: it repaired everything
  it owns, and it is forbidden to clobber the rest, so failing would make the documented setup
  step red with no action available to the person running it. Reversible in one line
  (`return 1 if (check and unwired_hooks) else 0`).
- **No new gate.** `--check` is not added to `automation/gates/run_gates.py`. CI never installs
  hooks, so the gate would be red by construction in every CI checkout; a worktree's hooks dir is
  not the primary checkout's either. It stays a local health command.
