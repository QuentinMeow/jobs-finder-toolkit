---
name: windows-environment
visibility: public
description: Set up, diagnose, and validate Windows development for this toolkit through WSL2. Use whenever runtime detection identifies Windows or WSL, or the user asks about Windows setup, WSL installation, migration from macOS, `/mnt/c` performance or permissions, Windows `TEMP`/`TMP`, Python or LibreOffice installation, Codex `bubblewrap` sandbox failures, or running repository gates on Windows.
---

# Windows Environment

Run this repository inside WSL2, not native PowerShell or Command Prompt. Confirm
the runtime before making repository changes; do not infer it from a Windows-looking
path or from the host application.

## Start with the environment doctor

From the repository root, run:

```bash
.venv/bin/python skills/windows-environment/scripts/doctor.py
```

If the venv does not exist yet, use `python3` for this one diagnostic. Read every
`FAIL` before changing files. `WARN` findings name optional capabilities or host
integration that the toolkit itself can run without.

Route by the reported runtime:

- **macOS** — the repository's default local environment. Continue with the normal
  skill; this Windows skill has no setup work to do.
- **Windows native** — stop before running Linux commands. Read
  [the WSL2 setup guide](references/setup.md) and guide the user through installing
  and opening Ubuntu under WSL2.
- **WSL** — fix blocking findings in the order below, then verify the toolkit.
- **Linux, not WSL** — use the normal Linux/CI workflow. Do not apply Windows fixes.

## Repair WSL in dependency order

1. Confirm WSL2 from PowerShell with `wsl -l -v`; upgrade the distro before repo work
   if it is still WSL1.
2. Keep the clone under the Linux filesystem, such as `~/code/`. A repo under
   `/mnt/c` has Windows filesystem performance and permission semantics.
3. Keep Python temporary files on Linux storage. If the doctor reports a Windows
   temp directory, use `/tmp` for `TMPDIR`, `TMP`, and `TEMP`. Ask before editing a
   shell startup file.
4. Install Python 3.11+, create `.venv`, install requirements, and always invoke
   repository scripts through `.venv/bin/python`.
5. Install Linux LibreOffice and prove the example DOCX-to-PDF render; Windows Word
   does not satisfy a Linux WSL process.
6. Install `bubblewrap` when Codex reports that its Linux sandbox cannot launch.
   Treat it as host tooling: verify `command -v bwrap`, restart WSL/Codex, and do not
   weaken repository guards to work around it.

Use [the setup guide](references/setup.md) for exact commands and official sources.

## Verify after repair

Run the checks from inside WSL and from the Linux-hosted clone:

```bash
.venv/bin/python skills/windows-environment/scripts/doctor.py
.venv/bin/python automation/bootstrap_overlay.py --check
.venv/bin/python skills/resume-writer/scripts/render.py examples/applications/6_drafted/example-corp-senior-software-engineer/
.venv/bin/python automation/gates/run_gates.py --impact-from origin/main --jobs 8
```

The gate runner automatically redirects child-process temp variables to `/tmp` when
WSL inherited a temp directory under `/mnt/<drive>`. The doctor still reports the
parent-shell problem because commands run outside the gate runner can otherwise
reproduce the same permission failure.

## Scope fixes honestly

- Fix small, deterministic repository gaps immediately and add a regression test.
- For an OS-wide change, WSL distro migration, repository move, or unresolved Codex
  sandbox integration, file a public task and the appropriate `needs-human` message
  with a reversible default. Do not silently change the user's Windows, WSL, Git, or
  shell configuration.
- Never interpret Windows filesystem permission behavior as proof that a Linux
  permission gate is wrong. Reproduce on `/tmp` or another Linux filesystem first.
