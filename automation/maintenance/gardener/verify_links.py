"""gardener routine: verify referenced paths, skill symlinks, and vendor drift.

EVERY TRACKED ``.md`` in the repo references toolkit paths in backticks — the agent
contract, the handbook, design docs, tasks, memory, templates, the README, each
skill. This routine checks that:

  * every backticked, repo-relative TOOLKIT path that looks like a real file/dir
    exists (resolving symlinks). Config-derived placeholders (``config.*()``,
    ``<slug>``/``<company>`` templates) and data/overlay trees (``applications/``,
    ``private/``, ``interviews/``, ``tmp/``) are skipped — they are runtime/illustrative,
    not shipped toolkit files. So are refs into a root this tree does not ship,
    git-ignored (overlay-only / per-user) paths, and — as ADVISORY, since plans
    and records name target and historical paths on purpose — unresolved refs
    sourced from ``design/``, ``tasks/``, ``message-queue/``, ``history/``,
    ``memory/decisions/``, ``evals/results/`` and ``roadmap/desired-state.md``.
    Every skipped class is COUNTED in the report, never silently dropped;
  * the ``.claude/skills/*`` and ``.cursor/skills/*`` compatibility symlinks resolve
    — and that there was something to resolve (no link root, an empty root, or a
    root tracked in git but missing from the worktree are each findings);
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
#
# A prefix is strict ONLY IN A TREE THAT HAS THAT ROOT (``_present_strict_prefixes``).
# The published export ships none of message-queue/, tasks/, memory/, roadmap/,
# history/ while AGENTS.md and the handbook necessarily name them, so making them
# strict everywhere would turn the PUBLISHED repo's gardener red — the same trap
# the reconciler's documented missing-root no-op exists to avoid. In the maintainer
# checkout every root is present, so every one of those refs IS verified.
STRICT_ROOT_PREFIXES = (
    "skills/", "automation/", ".claude-plugin/", "examples/",
    "handbook/", "design/", "roadmap/", "evals/", "templates/",
    "memory/", "tasks/", "message-queue/", "history/",
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

# Documents that describe a DIFFERENT tree than the one on disk — either a
# PROPOSED one (design programs and their execution plans, backlog/in-flight
# tasks, queue proposals and review items, the roadmap's desired state) or a PAST
# one (immutable ADRs, session handovers, dated eval-run records). A backticked
# path in one of these is a target to build or a record of what once was, NOT a
# claim that the file exists today: "create `automation/publish/review_gate.py`"
# is a plan, and requiring it to exist inverts the doc's meaning. Unresolved refs
# from these sources are counted and reported as ADVISORY, never a failure.
# Everything else — AGENTS.md, README, CONTRIBUTING, handbook/, templates/,
# skills/, examples/, evals/ protocol docs, memory/{facts,lessons,known-issues},
# roadmap/current-state.md — asserts CURRENT state and fails hard.
PLAN_OR_RECORD_SOURCES = (
    "design/", "tasks/", "message-queue/", "history/",
    "memory/decisions/", "evals/results/", "roadmap/desired-state.md",
)


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
    # ``references_private/`` is git-ignored, per-user and optional by contract
    # (the leak guard FAILS on any tracked file under it), so a doc naming one —
    # always as an example of the pattern — is not asserting that it exists.
    if "references_private" in token:
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


_FALLBACK_SKIP_DIRS = {".git", ".venv", "node_modules", "private", "tmp",
                       "applications", "interviews", "__pycache__"}


def _instruction_files() -> list[Path]:
    """Every TRACKED ``.md`` in the repo — each one is a reference SOURCE.

    Was ``AGENTS.md`` + ``skills/*/{SKILL,LESSONS,reference,AGENTS}.md`` (23 of
    ~155 docs), so a stale path in the handbook, a design doc, a task, a memory
    entry or the README was invisible. ``git ls-files`` (not ``rglob``) defines
    the set: it is exactly the publishable surface and it excludes the ignored
    trees (``private/``, ``tmp/``, ``.venv/``) for free. The rglob fallback keeps
    the routine usable in an exported tarball that is not a git checkout.
    """
    r = subprocess.run(["git", "-C", str(C.REPO_ROOT), "ls-files", "-z", "*.md"],
                       capture_output=True, text=True)
    if r.returncode == 0:
        files = [C.REPO_ROOT / p for p in r.stdout.split("\0") if p]
    else:  # not a git checkout (exported tree): walk, minus ignored/data trees
        files = [p for p in C.REPO_ROOT.rglob("*.md")
                 if not (_FALLBACK_SKIP_DIRS & set(
                     p.relative_to(C.REPO_ROOT).parts[:-1]))]
    return sorted(f for f in files if f.is_file() and not f.is_symlink())


def _resolves(token: str, bases: list[Path]) -> bool:
    rel = token.rstrip("/")
    return any((base / rel).exists() for base in bases)  # exists() follows symlinks


def _is_plan_or_record(f: Path) -> bool:
    """True when ``f`` describes a proposed or past tree (PLAN_OR_RECORD_SOURCES)."""
    try:
        rel = f.resolve().relative_to(C.REPO_ROOT).as_posix()
    except ValueError:
        return False
    return rel.startswith(PLAN_OR_RECORD_SOURCES)


def _present_strict_prefixes() -> tuple[str, ...]:
    """The STRICT_ROOT_PREFIXES whose root actually exists in THIS checkout."""
    return tuple(p for p in STRICT_ROOT_PREFIXES
                 if (C.REPO_ROOT / p.rstrip("/")).exists())


def _git_ignored(tokens: list[str]) -> set[str]:
    """Which tokens git ignores. Empty when this is not a git checkout.

    A git-ignored path is environment-dependent by construction — the private
    coding-interview skill symlinks, each ``skills/*/references_private/``, the
    personal job-search profiles. A doc naming one describes a path that exists
    only when the overlay is mounted, so it is never a claim that it exists here.
    """
    if not tokens:
        return set()
    r = subprocess.run(
        ["git", "-C", str(C.REPO_ROOT), "check-ignore", "--no-index", "--stdin"],
        input="\n".join(tokens), capture_output=True, text=True)
    if r.returncode not in (0, 1):  # 128 = not a git checkout / bad usage
        return set()
    return {line.strip() for line in r.stdout.splitlines() if line.strip()}


def check_references() -> tuple[list[dict], list[dict], dict[str, int]]:
    """Flag only GENUINE breaks: a repo-root-anchored toolkit path that resolves
    under no base. Skill-relative and documented-optional refs resolve or are
    treated as relative (not broken) — see STRICT_ROOT_PREFIXES / _bases_for.

    Four classes never fail the gate, each counted so nothing is silently dropped:
      * ``private/`` overlay refs when the overlay is not mounted ("overlay");
      * refs under a strict root this tree does not ship ("absent-root") — the
        published export has no message-queue/, tasks/, memory/, roadmap/, history/;
      * refs git ignores ("git-ignored") — overlay-only symlinks and per-user dirs;
      * unresolved refs whose SOURCE is a plan or a record (PLAN_OR_RECORD_SOURCES),
        which name target and historical paths on purpose ("advisory").

    Returns ``(broken, advisory, skipped_counts)``.
    """
    broken: list[dict] = []
    advisory: list[dict] = []
    skipped = {"overlay": 0, "absent-root": 0, "git-ignored": 0}
    overlay_mounted = _overlay_mounted()
    strict = _present_strict_prefixes()
    absent = tuple(p for p in STRICT_ROOT_PREFIXES if p not in strict)

    # ``private/**`` is git-ignored wholesale in the public tree, so the
    # git-ignored narrowing must NOT touch overlay refs — the overlay-mounted
    # branch above already decides those. Only public-tree candidates are filtered.
    candidates: list[tuple[list[dict], dict]] = []
    for f in _instruction_files():
        bases = _bases_for(f)
        sink = advisory if _is_plan_or_record(f) else broken
        seen: set[str] = set()
        for lineno, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            for token in BACKTICK_RE.findall(line):
                token = token.strip()
                if token in seen or not _is_checkable(token):
                    continue
                seen.add(token)
                hit = {"file": C.rel(f), "line": lineno, "ref": token}
                if token.startswith(OVERLAY_PREFIX):
                    if not overlay_mounted:
                        skipped["overlay"] += 1
                    elif not _resolves(token, bases):
                        sink.append(hit)
                    continue
                if _resolves(token, bases):
                    continue
                if token.startswith(absent):
                    skipped["absent-root"] += 1
                elif token.startswith(strict):
                    candidates.append((sink, hit))

    ignored = _git_ignored(sorted({h["ref"].rstrip("/") for _, h in candidates}))
    for sink, hit in candidates:
        if hit["ref"].rstrip("/") in ignored:
            skipped["git-ignored"] += 1
        else:
            sink.append(hit)
    return broken, advisory, skipped


# Editor compatibility trees carrying the ``skills/*`` symlinks. At least one must
# exist: finding none used to mean "all resolve".
SYMLINK_ROOTS = (".claude/skills", ".cursor/skills")


def _tracked_symlink_roots() -> set[str] | None:
    """Which SYMLINK_ROOTS git tracks, or None when this is not a git checkout."""
    r = subprocess.run(["git", "-C", str(C.REPO_ROOT), "ls-files", "-z",
                        *SYMLINK_ROOTS], capture_output=True, text=True)
    if r.returncode != 0:
        return None
    tracked = set()
    for path in r.stdout.split("\0"):
        for root in SYMLINK_ROOTS:
            if path.startswith(root + "/"):
                tracked.add(root)
    return tracked


def check_symlinks() -> list[dict]:
    """Unresolved skill compat symlinks — and a FINDING when nothing was verified.

    Was fail-open in three ways, all of which reported "skill symlinks: all
    resolve" after checking nothing: both roots absent (a restructure renames or
    drops them), a root present but empty, and a root tracked in git yet missing
    from the working tree. Each is now its own finding.
    """
    bad: list[dict] = []
    present = {r: C.REPO_ROOT / r for r in SYMLINK_ROOTS
               if (C.REPO_ROOT / r).is_dir()}
    tracked = _tracked_symlink_roots()

    if tracked is not None:
        for root in sorted(tracked - set(present)):
            bad.append({"link": root,
                        "target": "TRACKED in git but absent from the working tree"})
    if not present:
        bad.append({"link": " / ".join(SYMLINK_ROOTS),
                    "target": "NO skill link root exists — nothing was verified"})

    for root, skdir in sorted(present.items()):
        links = [p for p in sorted(skdir.iterdir()) if p.is_symlink()]
        if not links:
            bad.append({"link": root, "target": "contains no skill symlinks — "
                                                "nothing was verified"})
        for link in links:
            if not link.resolve().exists():
                # NOT C.rel(): it resolve()s, which would name the missing TARGET
                # instead of the broken link the reader has to repair.
                bad.append({"link": link.relative_to(C.REPO_ROOT).as_posix(),
                            "target": str(link.readlink())})
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
    broken, advisory, skipped = check_references()
    bad_links = check_symlinks()
    vendor_rc, vendor_msg = check_vendor()

    print(f"  backticked toolkit refs checked across {len(_instruction_files())} tracked .md files")
    labels = {"overlay": "private/ overlay not mounted",
              "absent-root": "root not shipped in this tree",
              "git-ignored": "git-ignored (overlay-only / per-user)"}
    for key, count in skipped.items():
        if count:
            print(f"  skipped refs — {labels[key]}: {count}")
    if advisory:
        print(f"  advisory (target/historical paths named by plans and records): {len(advisory)}")
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
