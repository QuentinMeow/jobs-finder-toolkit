# Worklog — 2026-08-25-install-git-ws-alias

## 2026-08-25 — session 1 (Codex)

- Confirmed the dashboard implementation is on public `main` through merge PR #338.
- Traced `git ws` to `alias.ws` in this checkout's `.git/config`; no tracked setup path created it for another clone.
- Chose the existing bootstrap command as the owner of the repository-local alias because it already installs checkout-specific Git metadata.
- Added non-destructive alias installation, health-check reporting, and coverage for missing, correct, and conflicting aliases; the end-to-end test invokes `git ws` successfully.
- The focused hook/bootstrap suite passed. A complete gate run inside the app was red only where LibreOffice could not access macOS LaunchServices and where the mounted overlay had no `config.yaml`; the existing backlog task `2026-08-22-the-shared-suite-is-red-for-the-owner-and-green-for-every-agent` already records the latter defect.
- Re-ran the complete selected gate set at commit `28b8e6f` in a detached config-less checkout with LibreOffice access; every selected gate passed. The armed pre-push leak guard then passed the exact outgoing Git object.
- Opened public PR #368 against `main`.

## 2026-08-25 — session 2 (Codex)

- Reopened the user-visible path after a second laptop pulled merged PR #368 and still could not run `git ws`.
- Cloned public `main` into an empty temporary directory. The dashboard script was present, `git ws` failed before bootstrap, `python3 automation/bootstrap_overlay.py` installed the checkout-local alias, and the next `git ws --no-color` succeeded.
- Kept bootstrap as the installer because Git intentionally neither clones `.git/config` nor executes repository code during clone or pull; a zero-step repository-local alias is not available through Git's clone model.
- Moved the one-time bootstrap into the fresh-clone quickstart and changed contributor setup from optional wording to an explicit per-checkout requirement.
