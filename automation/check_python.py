#!/usr/bin/env python3
"""Refuse to build a virtualenv on a Python this toolkit cannot run.

Run this BEFORE ``python3 -m venv .venv`` (the README quickstart chains the two
with ``&&``, so a failure here means no ``.venv/`` is ever created):

    python3 automation/check_python.py && python3 -m venv .venv

Why this exists: on a stock macOS box, bare ``python3`` is often an ancient
interpreter (3.7 is still common). ``python3 -m venv .venv`` on it EXITS 0 and
produces a perfectly working-looking environment whose pip is 19.x — and the
first sign of trouble arrives much later, as an unrelated-looking
``No matching distribution found for python-jobspy`` from ``pip install -r
requirements.txt``. That message names the wrong cause, so the failure costs a
new user an hour. This check names the real one, immediately, and stops.

THIS FILE MUST STAY PARSEABLE BY OLD PYTHONS. It is executed BY the interpreter
under suspicion, so a syntax error is not a report — it is a crash that hides
the very thing being reported. That rules out every post-3.7 syntax feature:
no walrus (3.8), no ``f"{x=}"`` (3.8), no ``X | None`` annotations (3.10), no
``match`` (3.10). Keep it stdlib-only and keep the formatting on ``%``.
``automation/hooks/tests/test_check_python.py`` re-parses this file with
``ast.parse(..., feature_version=(3, 7))`` so the rule is enforced, not merely
requested.
"""

import sys

MINIMUM = (3, 11)

# Interpreters worth suggesting, newest first: these are the names a modern
# CPython install puts on PATH alongside the (possibly ancient) ``python3``.
CANDIDATES = ("python3.14", "python3.13", "python3.12", "python3.11")


def running_version():
    """This interpreter's version as ``major.minor.micro``."""
    return "%d.%d.%d" % (sys.version_info[0], sys.version_info[1],
                         sys.version_info[2])


def minimum_version():
    """The required floor, rendered the way the docs write it."""
    return "%d.%d" % (MINIMUM[0], MINIMUM[1])


def newer_interpreters():
    """Names of modern interpreters found on PATH, newest first (may be empty)."""
    try:
        from shutil import which
    except ImportError:                      # pragma: no cover - stdlib always has it
        return []
    found = []
    for name in CANDIDATES:
        if which(name):
            found.append(name)
    return found


def failure_report(found):
    """The stderr text for a too-old interpreter, given the PATH search result."""
    lines = [
        "ERROR: this toolkit needs Python %s+, but the interpreter running this"
        " check is %s" % (minimum_version(), running_version()),
        "       (%s)." % sys.executable,
        "",
        "Do NOT create the venv with it. `python3 -m venv .venv` would exit 0"
        " here and",
        "install an obsolete pip, and the damage would only surface later as a"
        " confusing",
        "`No matching distribution found for python-jobspy` from the"
        " requirements install.",
        "",
    ]
    if found:
        lines.append("Use a newer interpreter already on this machine:")
        lines.append("    %s -m venv .venv && .venv/bin/pip install -r"
                     " requirements.txt" % found[0])
    else:
        lines.append("No Python %s+ interpreter was found on PATH. Install one,"
                     " then re-run:" % minimum_version())
        lines.append("    macOS:       brew install python@3.13")
        lines.append("    Ubuntu/WSL:  sudo apt install python3.13-venv")
        lines.append("    any platform: uv venv --python 3.13"
                     "   (https://docs.astral.sh/uv/)")
    return "\n".join(lines)


def main(argv=None):
    """Exit 0 when this interpreter is new enough; 1 with an explanation if not."""
    if sys.version_info[:2] >= MINIMUM:
        print("OK: Python %s at %s (>= %s required)."
              % (running_version(), sys.executable, minimum_version()))
        return 0
    sys.stderr.write(failure_report(newer_interpreters()) + "\n")
    return 1


if __name__ == "__main__":
    sys.exit(main())
