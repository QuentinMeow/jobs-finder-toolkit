#!/usr/bin/env python3
"""Diagnose whether this toolkit is ready to run on Windows through WSL2."""
from __future__ import annotations

import argparse
import os
import platform
import re
import shutil
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Mapping


@dataclass(frozen=True)
class Check:
    status: str
    label: str
    detail: str
    fix: str | None = None


def kernel_release() -> str:
    try:
        return Path("/proc/sys/kernel/osrelease").read_text(encoding="utf-8").strip()
    except OSError:
        return platform.release()


def classify_runtime(
    *,
    system_name: str | None = None,
    release: str | None = None,
    environ: Mapping[str, str] | None = None,
) -> str:
    system_name = system_name or platform.system()
    release = release if release is not None else kernel_release()
    environ = os.environ if environ is None else environ
    if system_name == "Darwin":
        return "macos"
    if system_name == "Windows":
        return "windows-native"
    if system_name == "Linux" and (
        "microsoft" in release.lower() or environ.get("WSL_DISTRO_NAME")
    ):
        return "wsl"
    if system_name == "Linux":
        return "linux"
    return "other"


def is_windows_mount(path: Path) -> bool:
    return bool(re.match(r"^/mnt/[a-z](?:/|$)", path.absolute().as_posix().lower()))


def default_repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def inspect_environment(
    repo: Path,
    *,
    runtime: str | None = None,
    release: str | None = None,
    temp_dir: Path | None = None,
    which: Callable[[str], str | None] = shutil.which,
) -> list[Check]:
    repo = repo.expanduser().absolute()
    release = release if release is not None else kernel_release()
    runtime = runtime or classify_runtime(release=release)
    temp_dir = temp_dir or Path(tempfile.gettempdir())
    checks: list[Check] = []

    if runtime == "wsl":
        checks.append(Check("PASS", "runtime", f"WSL detected ({release})"))
        if "wsl2" not in release.lower():
            checks.append(Check(
                "WARN", "WSL version", "the kernel string does not prove WSL2",
                "Run `wsl -l -v` in PowerShell and require version 2.",
            ))
    elif runtime == "windows-native":
        checks.append(Check(
            "FAIL", "runtime", "native Windows is not the toolkit execution environment",
            "Install/open Ubuntu under WSL2, then run this doctor inside WSL.",
        ))
    elif runtime == "macos":
        checks.append(Check("PASS", "runtime", "macOS detected; use the default setup path"))
    elif runtime == "linux":
        checks.append(Check("WARN", "runtime", "Linux detected, but not WSL; Windows fixes do not apply"))
    else:
        checks.append(Check("FAIL", "runtime", f"unsupported runtime: {runtime}"))

    if not repo.is_dir() or not (repo / ".git").exists():
        checks.append(Check("FAIL", "repository", f"not a Git checkout: {repo}"))
    elif runtime == "wsl" and is_windows_mount(repo):
        checks.append(Check(
            "FAIL", "repository storage", f"repository is on a Windows mount: {repo}",
            "Clone it under `~/code/` inside the WSL filesystem.",
        ))
    else:
        checks.append(Check("PASS", "repository storage", str(repo)))

    if runtime == "wsl" and is_windows_mount(temp_dir):
        checks.append(Check(
            "FAIL", "temporary directory", f"Python selected Windows storage: {temp_dir}",
            "Set `TMPDIR=/tmp`, `TMP=/tmp`, and `TEMP=/tmp`.",
        ))
    else:
        checks.append(Check("PASS", "temporary directory", str(temp_dir)))

    version = sys.version_info
    if version >= (3, 11):
        checks.append(Check("PASS", "Python", platform.python_version()))
    else:
        checks.append(Check(
            "FAIL", "Python", platform.python_version(),
            "Install Python 3.11+ and recreate `.venv`.",
        ))

    venv_python = repo / ".venv/bin/python"
    if venv_python.is_file() and os.access(venv_python, os.X_OK):
        checks.append(Check("PASS", "repo venv", str(venv_python)))
    else:
        checks.append(Check(
            "FAIL", "repo venv", f"missing executable: {venv_python}",
            "Run `python3 -m venv .venv` and `.venv/bin/pip install -r requirements.txt`.",
        ))

    for command, required, fix in (
        ("git", True, "Install `git` inside WSL."),
        ("gh", False, "Install GitHub CLI inside WSL for PR workflows."),
        ("bwrap", False, "Install Ubuntu's `bubblewrap` package for the Codex sandbox."),
    ):
        found = which(command)
        if found:
            checks.append(Check("PASS", command, found))
        else:
            checks.append(Check("FAIL" if required else "WARN", command, "not found", fix))

    office = which("soffice") or which("libreoffice")
    if office:
        checks.append(Check("PASS", "LibreOffice", office))
    else:
        checks.append(Check(
            "FAIL", "LibreOffice", "neither `soffice` nor `libreoffice` is on PATH",
            "Install Ubuntu's `libreoffice` package inside WSL.",
        ))
    return checks


def print_report(checks: Iterable[Check]) -> int:
    checks = list(checks)
    for check in checks:
        print(f"[{check.status}] {check.label}: {check.detail}")
        if check.fix:
            print(f"       Fix: {check.fix}")
    failures = [check for check in checks if check.status == "FAIL"]
    warnings = [check for check in checks if check.status == "WARN"]
    if failures:
        print(f"NOT READY: {len(failures)} blocking finding(s), {len(warnings)} warning(s)")
        return 1
    print(f"READY: no blocking findings, {len(warnings)} warning(s)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=default_repo_root())
    args = parser.parse_args(argv)
    return print_report(inspect_environment(args.repo))


if __name__ == "__main__":
    raise SystemExit(main())
