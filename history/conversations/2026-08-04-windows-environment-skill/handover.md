# Windows environment skill and WSL compatibility

Date: 2026-08-04

## Tasks

- None. This was a direct owner request; no backlog task was claimed.

## What happened

- Added a public `windows-environment` skill with official WSL2 setup guidance and a deterministic environment doctor.
- Made runtime confirmation a required top-level-agent preflight: macOS remains the default, Windows routes through WSL2 and the new skill.
- Fixed WSL gate failures caused by Python inheriting a Windows-mounted temporary directory. Gate subprocesses now use `/tmp` automatically, with regression coverage.
- Replaced remaining public setup examples that used bare `python` or `pip` with the repository venv.
- Verified the doctor, gate-runner tests, manifests, links, instruction budgets, and reconciler. The generic skill-creator validator rejects this repo's required `visibility` frontmatter key, so repository-native manifest/export gates are authoritative.

## Where it stands

- The Windows/WSL implementation is complete and ready for the public PR.
- The current WSL host is ready when `TMPDIR`, `TMP`, and `TEMP` resolve to `/tmp`; missing `bubblewrap` remains an optional-host-tool warning for the toolkit but explains why Codex's local sandbox cannot launch.
- No large unresolved Windows issue required a task or a new `needs-human` message.

## Decisions made

- Support Windows only through WSL2; do not add a native PowerShell execution path.
- Treat a clone or Python temp directory under `/mnt/<drive>` as blocking in the doctor, while repairing only gate child-process temp automatically.
- Keep persistent shell configuration and WSL installation as user-owned host changes; provide commands but never apply them silently.
- Eval gate: skipped — the `ask-me-anything` change is an eight-line additive setup note, and `windows-environment` has no canary set; deterministic tests and publication gates cover the new behavior.

## If continuing

- Open the public PR, wait for GitHub checks, then link it from the existing private PR.
- Re-run the environment doctor after installing `bubblewrap` or changing WSL shell temp configuration.

## Dead ends

- Codex's normal command sandbox could not start because no `bwrap` binary is installed. Commands were run through approved escalation; repository safeguards were not disabled.
- Running permission-fixture tests with Python temp on the Windows mount produced false failures; reproducing on `/tmp` isolated the host-filesystem cause.

## Needs attention

- No new owner action was filed for this work.
- 29 pending · top: `job-search-us-only-default-asymmetry` — leaving it unanswered can silently narrow searches for profiles that omit the US-only key.
