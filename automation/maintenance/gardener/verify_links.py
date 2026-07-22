"""gardener routine: verify referenced paths, skill symlinks, and vendor drift.

Instruction files (AGENTS.md, SKILL.md, LESSONS.md, reference.md) reference toolkit
paths in backticks. This routine checks that:

  * every backticked, repo-relative TOOLKIT path that looks like a real file/dir
    exists (resolving symlinks). Config-derived placeholders (``config.*()``,
    ``<slug>``/``<company>`` templates) and data/overlay trees (``applications/``,
    ``private/``, ``interviews/``, ``tmp/``) are skipped — they are runtime/illustrative,
    not shipped toolkit files;
  * the ``.claude/skills/*`` and ``.cursor/skills/*`` compatibility symlinks resolve;
  * vendored copies are in sync (``sync_vendored.py --check``).

Exit 1 on any broken reference / unresolved symlink / vendor drift; else exit 0.
Report-only otherwise (it fixes nothing).

Usage:
    .venv/bin/python automation/maintenance/gardener/verify_links.py
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common as C  # noqa: E402

BACKTICK_RE = re.compile(r"`([^`]+)`")

# Repo-root-anchored TOOLKIT prefixes: a backticked path starting with one of these
# MUST exist from the repo root. A break here (e.g. AGENTS.md naming a renamed
# script) is genuine. Bare relative fragments (`scripts/x.py`, `source/…`,
# `profiles/…`, `_vendor/…`) are NOT in this set — they resolve against a skill base
# (below) or are documented optional/ephemeral references, and never hard-fail.
STRICT_ROOT_PREFIXES = (
    "skills/", "automation/shared/", "automation/vendoring/",
    "automation/maintenance/", "automation/metrics/", "automation/publish/",
    "hooks/", "docs/", ".claude-plugin/", "examples/",
)
# Runtime data / scratch trees — never verified (illustrative or absent in a public
# checkout). The overlay's DATA/product trees are illustrative too, so their
# ``private/`` forms are skipped exactly like the bare ones. ``private/`` is NOT
# blanket-skipped: genuine overlay TOOLKIT paths (the maintainer-only design docs
# under ``private/docs/``) fall through to OVERLAY_PREFIX and are verified ONLY when
# the overlay is mounted (otherwise counted "overlay-skipped" — a clean pass for
# contributors).
SKIP_PREFIXES = ("applications/", "interviews/", "tmp/",
                 ".agents/inputs/", ".git/", ".venv/",
                 "private/applications/", "private/interviews/",
                 "private/job-search/", "private/tmp/")
SKILLS_ROOT = "skills"

# Backticked refs into the private overlay (maintainer-only design docs, real
# products). Present only when the overlay is mounted at ``private/``.
OVERLAY_PREFIX = "private/"


def _overlay_mounted() -> bool:
    """True when the private overlay is mounted (a contributor checkout has none)."""
    return (C.REPO_ROOT / "private").is_dir()


def _is_checkable(token: str) -> bool:
    """True for a concrete-looking repo path (not a placeholder / expression)."""
    if "/" not in token:
        return False
    if any(c in token for c in "<>(){}*|?`$ \t…"):
        return False
    if "config." in token or "layout." in token or "check." in token:
        return False
    if not re.fullmatch(r"[A-Za-z0-9._/\-]+", token.rstrip("/")):
        return False
    if token.startswith(SKIP_PREFIXES):
        return False
    return True


def _bases_for(f: Path) -> list[Path]:
    """Resolution bases for references inside file ``f``.

    Always the repo root and the file's own directory. When ``f`` lives under a
    skill, also the skill root, its ``scripts/`` subdir, and the skills root — so
    skill-relative refs (`scripts/x.py`, `_vendor/y.py`, `sibling-skill/…`) resolve.
    """
    bases = [C.REPO_ROOT, f.parent]
    try:
        parts = f.resolve().relative_to(C.REPO_ROOT).parts
    except ValueError:
        return bases
    if len(parts) >= 2 and parts[0] == "skills":
        skill_root = C.REPO_ROOT / parts[0] / parts[1]
        bases += [skill_root, skill_root / "scripts", C.REPO_ROOT / SKILLS_ROOT]
    return bases


def _instruction_files() -> list[Path]:
    files = [C.REPO_ROOT / "AGENTS.md"]
    skills = C.REPO_ROOT / "skills"
    for name in ("SKILL.md", "LESSONS.md", "reference.md", "AGENTS.md"):
        files.extend(sorted(skills.glob(f"*/{name}")))
    return [f for f in files if f.is_file()]


def _resolves(token: str, bases: list[Path]) -> bool:
    rel = token.rstrip("/")
    return any((base / rel).exists() for base in bases)  # exists() follows symlinks


def check_references() -> tuple[list[dict], int]:
    """Flag only GENUINE breaks: a repo-root-anchored toolkit path that resolves
    under no base. Skill-relative and documented-optional refs resolve or are
    treated as relative (not broken) — see STRICT_ROOT_PREFIXES / _bases_for.

    ``private/`` overlay refs (maintainer-only design docs) are checked ONLY when
    the overlay is mounted; without it they are counted as "overlay-skipped" so a
    contributor checkout (no ``private/``) still passes clean. Returns
    ``(broken, overlay_skipped)``.
    """
    broken: list[dict] = []
    overlay_skipped = 0
    overlay_mounted = _overlay_mounted()
    for f in _instruction_files():
        bases = _bases_for(f)
        seen: set[str] = set()
        for lineno, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            for token in BACKTICK_RE.findall(line):
                token = token.strip()
                if token in seen or not _is_checkable(token):
                    continue
                seen.add(token)
                if token.startswith(OVERLAY_PREFIX):
                    if not overlay_mounted:
                        overlay_skipped += 1
                    elif not _resolves(token, bases):
                        broken.append({"file": C.rel(f), "line": lineno, "ref": token})
                    continue
                if _resolves(token, bases):
                    continue
                if token.startswith(STRICT_ROOT_PREFIXES):
                    broken.append({"file": C.rel(f), "line": lineno, "ref": token})
    return broken, overlay_skipped


def check_symlinks() -> list[dict]:
    bad: list[dict] = []
    for editor in (".claude", ".cursor"):
        skdir = C.REPO_ROOT / editor / "skills"
        if not skdir.is_dir():
            continue
        for link in sorted(skdir.iterdir()):
            if link.is_symlink() and not link.resolve().exists():
                bad.append({"link": C.rel(link), "target": str(link.readlink())})
    return bad


def check_vendor() -> tuple[int, str]:
    script = C.REPO_ROOT / "automation" / "vendoring" / "sync_vendored.py"
    if not script.is_file():
        return 0, "sync_vendored.py not found (skipped)"
    r = subprocess.run([sys.executable, str(script), "--check"],
                       capture_output=True, text=True)
    return r.returncode, (r.stdout + r.stderr).strip()


def run() -> int:
    C.print_header("verify-links (report-only)", apply=False)
    broken, overlay_skipped = check_references()
    bad_links = check_symlinks()
    vendor_rc, vendor_msg = check_vendor()

    print(f"  backticked toolkit refs checked across {len(_instruction_files())} files")
    if overlay_skipped:
        print(f"  overlay-skipped refs: {overlay_skipped} (private/ overlay not mounted)")
    if broken:
        print(f"  BROKEN references: {len(broken)}")
        for b in broken:
            print(f"    {b['file']}:{b['line']}  ->  {b['ref']}")
    else:
        print("  references: all resolve")

    if bad_links:
        print(f"  BROKEN skill symlinks: {len(bad_links)}")
        for b in bad_links:
            print(f"    {b['link']} -> {b['target']}")
    else:
        print("  skill symlinks: all resolve")

    print(f"  vendor drift check: {'OK' if vendor_rc == 0 else 'FAIL'} — {vendor_msg}")

    failed = bool(broken) or bool(bad_links) or vendor_rc != 0
    print("\n  " + ("FAIL: broken references / symlinks / drift found."
                    if failed else "OK: links, symlinks, and vendored copies verified."))
    return 1 if failed else 0


def main(argv=None) -> int:
    argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter).parse_args(argv)
    return run()


if __name__ == "__main__":
    raise SystemExit(main())
