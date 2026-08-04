# Windows + WSL2 setup

## 1. Install and confirm WSL2

Open PowerShell as Administrator:

```powershell
wsl --install -d Ubuntu
```

Restart Windows if prompted, open Ubuntu, and create the Linux user when asked. Then
confirm the distro version from PowerShell:

```powershell
wsl --update
wsl -l -v
```

The Ubuntu row must show version `2`. Microsoft documents the current installation
flow in [Install WSL](https://learn.microsoft.com/windows/wsl/install) and
[Set up a WSL development environment](https://learn.microsoft.com/windows/wsl/setup/environment).

## 2. Install Linux-side dependencies

Run inside Ubuntu/WSL:

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip git zsh libreoffice bubblewrap
```

LibreOffice and `bubblewrap` are Ubuntu packages. GitHub CLI is optional for normal
toolkit use but required for PR work; use GitHub's maintained
[Debian/Ubuntu installation instructions](https://github.com/cli/cli/blob/trunk/docs/install_linux.md),
then authenticate with `gh auth login`.

## 3. Clone into the Linux filesystem

Do not run Linux builds from `/mnt/c`. Microsoft recommends keeping Linux-tool repos
in the WSL filesystem because Windows-mounted drives have different performance and
permission behavior. See [WSL file-system guidance](https://learn.microsoft.com/windows/wsl/filesystems).

```bash
mkdir -p ~/code
cd ~/code
git clone https://github.com/<owner>/jobs-finder-toolkit.git
cd jobs-finder-toolkit
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python automation/bootstrap_overlay.py
```

Open this Linux path through the editor's WSL integration. Windows Explorer can reach
it through `\\wsl$`, but the repository remains stored inside Linux.

## 4. Keep temporary files on Linux storage

Check what Python selected:

```bash
python3 -c 'import tempfile; print(tempfile.gettempdir())'
```

If it prints `/mnt/<drive>/...`, set these variables for the current shell:

```bash
export TMPDIR=/tmp
export TMP=/tmp
export TEMP=/tmp
```

Add those lines to the active shell's `~/.zshrc` or `~/.bashrc` only after the user
approves a persistent change. Windows-mounted files commonly do not preserve the Unix
permission fixtures used by this repository; Microsoft documents the underlying DrvFS
permission model in [File Permissions for WSL](https://learn.microsoft.com/windows/wsl/file-permissions).

## 5. Diagnose and prove the setup

```bash
.venv/bin/python skills/windows-environment/scripts/doctor.py
.venv/bin/python automation/bootstrap_overlay.py --check
.venv/bin/python skills/resume-writer/scripts/render.py examples/applications/6_drafted/example-corp-senior-software-engineer/
```

If Codex still says `bubblewrap` is unavailable after `command -v bwrap` succeeds,
close Codex, run `wsl.exe --shutdown` from PowerShell, reopen Ubuntu, then reopen the
Linux-hosted repository. Do not disable the sandbox or repository gates as a fix.
