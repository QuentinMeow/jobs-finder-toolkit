"""Allowlist-based exporter: produce a clean PUBLIC checkout of this toolkit.

This exporter seeded the public toolkit repo from the pre-split combined repo
(fresh, PII-free history) and remains useful post-split: the leak-guard test
suite drives it end-to-end, and it can produce a sanitized copy of any checkout
(e.g. one that still holds an in-place overlay). It copies ONLY known-public
paths (an explicit ALLOWLIST) into a fresh destination directory, applies a
denylist to scrub anything personal that slipped inside an allowlisted tree,
ships this repo's tracked ``.gitignore``, regenerates the ``.claude/skills`` /
``.cursor/skills`` compat symlinks for the PUBLIC skills, and (optionally)
``git init`` + runs the leak guard (``check_public.py``) before committing.

Design rules:
  * The ALLOWLIST wins: nothing is ever copied unless it lives under an
    allowlisted path. When in doubt, exclude.
  * The tree is enumerated through ``git ls-files``, never ``os.walk``: only
    TRACKED files can ship. A scratch file, a scraped JD, or a personal profile
    symlink dropped into an allowlisted directory is git-ignored/untracked and
    therefore invisible to the export by construction.
  * An allowlisted path that resolves to nothing is REPORTED, never silently
    skipped — a renamed or typo'd entry used to ship zero files and say nothing.
    ``--strict`` turns those warnings into a refusal, before ``--force`` touches
    the destination.
  * The DESTINATION is decided twice: a blocklist of paths that are never a
    legitimate export target (the checkout, the private overlay, your home,
    another git checkout) refuses first, and then ``--force`` may DELETE only an
    empty directory or one carrying this exporter's own marker file. See
    ``forbidden_destination`` / ``overwrite_refusal``.
  * Which ``skills/<name>`` trees ship is DERIVED from each SKILL.md's
    ``visibility:`` frontmatter (``sync_skill_manifests``), never restated here.
  * The DENYLIST is applied AFTER the allowlist, per file: ``__pycache__``,
    ``*.pyc``, ``.DS_Store``, the owner's personal job-search profiles, and any
    file whose PATH or (text) CONTENT trips the personal-identity token screen
    shared with ``check_public.py``.
  * The leak guard is the final gate under ``--git-init``: if it FAILS the export
    is NOT committed and the exporter exits nonzero.

Usage:
    .venv/bin/python automation/publish/export_public.py --dest <dir> [--git-init] [--force] [--strict]
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

# Make the sibling leak guard importable so we reuse ONE source of truth for the
# personal-identity token list and the binary/text helpers, and the sibling
# manifest module so the PUBLIC skill list is derived from SKILL.md frontmatter
# instead of restated here (they disagreed for months; search-recall-audit
# existed but had never shipped).
sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_public  # noqa: E402
import sync_skill_manifests  # noqa: E402

# automation/publish/export_public.py -> repo root is two parents up.
REPO_ROOT = Path(__file__).resolve().parents[2]

# Allowlisted individual files (repo-root-relative). Must be TRACKED.
ALLOWLIST_FILES = [
    "AGENTS.md",
    # The root shim that makes Claude Code load AGENTS.md (a one-line @-import).
    # Without it a fresh public clone silently boots with no agent contract.
    "CLAUDE.md",
    "CONTRIBUTING.md",
    "README.md",
    "LICENSE",
    "requirements.txt",
    "config.example.yaml",
    # The one-shot "make my checkout work" step README.md / CONTRIBUTING.md /
    # docs/handbook/private-overlay.md all tell a new user to run.
    "automation/bootstrap_overlay.py",
    # The setup preflight the README quickstart and CONTRIBUTING's dev-setup block
    # both invoke by path, on line 2 of the very first thing a new user runs. It is
    # also the one script in the tree that must run BEFORE the venv exists, so a
    # mirror without it ships a quickstart whose second command is missing — and
    # the exported verify_links.py reads those fences, so the mirror would go red.
    "automation/check_python.py",
]

# Allowlisted directory trees (every TRACKED file under them, denylist-filtered).
# The public skills are appended at call time by ``allowlist_dirs()`` — see
# ``public_skills()``.
ALLOWLIST_DIRS = [
    "examples",
    "automation/shared",
    "automation/vendoring",
    "automation/gardener",
    "automation/search-recall-audit",
    "automation/company-levels",
    "automation/metrics",
    "automation/publish",
    "automation/store",
    # Ships next to ``evals`` because it is that tree's tooling. The exported
    # ``evals/results/TEMPLATE.md`` tells its reader to run
    # ``automation/evals/record_pins.py``, so a mirror without this entry would
    # ship a template naming a command it does not contain — and the exported
    # copy of ``verify_links.py`` reads that fence, so it would go red there.
    "automation/evals",
    "evals",
    # The local gate runner. It ships because ``ci.yml`` runs its tests (step 2c) and
    # ``docs/handbook/command-cookbook.md`` names its path — the mirror runs this same
    # workflow and the same markdown-link check, so omitting it would red the exported
    # repo's own CI twice over.
    "automation/gates",
    # Pull-request impact classification. It ships with the workflow that invokes
    # it; omitting this directory would make the exported mirror's CI reference a
    # command the mirror does not contain.
    "automation/ci",
    "automation/hooks",
    "automation/reconcile",
    # Timeless tooling with no personal data: the read-only post-merge cutover
    # planner and the validation profile. It ships because the handbook pages
    # that DO ship (post-merge-cutover.md, command-cookbook.md, repo-map.md) name
    # these commands — omitting it leaves 13 broken references inside the export.
    "automation/cutover",
    # The local Git dashboard and its synthetic tests. The exported handbook names
    # this command, and the maintenance lane runs its tests through run_gates.py.
    "automation/workspace",
    "templates",
    ".github",
    ".claude-plugin",
    # The two human-doc trees that ship. NOT a bare ``docs`` — that would newly
    # export ``docs/roadmap/``, which has never been published (it names in-flight
    # work), so the parent is spelled out one shipping child at a time.
    "docs/handbook",
    "docs/designs",
]


def public_skills() -> list[str]:
    """The PUBLIC skills that ship, from ``skills/*/SKILL.md`` frontmatter."""
    return sync_skill_manifests.public_skills(REPO_ROOT)


def allowlist_dirs() -> list[str]:
    """Allowlisted trees + one ``skills/<name>`` entry per PUBLIC skill."""
    return ALLOWLIST_DIRS + [f"skills/{skill}" for skill in public_skills()]

# The job-search profiles folder is allowlisted, but only these generic profile
# files are PUBLIC. Any OTHER file directly under it is a personal profile and is
# kept OUT — expressed as an allowlist so this exporter never has to spell out (and
# therefore never carries) an owner's personal filename/token.
PROFILES_DIR = "skills/job-search/profiles"
PUBLIC_PROFILE_FILES = {"example.yaml", "_TEMPLATE.yaml", "README.md"}

# Files exempt from the token-CONTENT screen because they legitimately carry the
# personal-token list itself (the leak-guard config). Their PATHS are still
# screened. Mirrors ``check_public.GUARD_REL_PATH`` so the guard we ship is copied
# even though it embeds the token list; every other file (this exporter included)
# must be token-free so both the exporter and the guard agree.
TOKEN_CONTENT_EXEMPT = {check_public.GUARD_REL_PATH}

# The public .gitignore shipped into <dest> is this repo's OWN tracked ``.gitignore``
# — a single source of truth, so the exported mirror and this checkout can never
# drift. (The tracked file already contains only public/overlay-continuity rules.)
GITIGNORE_REL = ".gitignore"

# ── destination safety ───────────────────────────────────────────────────────
# The exporter CREATES a tree at --dest and, under --force, DELETES whatever is
# already there. ``shutil.rmtree`` is irreversible, so the destination has to
# clear TWO independent rules:
#
#   1. A BLOCKLIST of destinations that are never legitimate
#      (``forbidden_destination``). It runs FIRST — before the arming gate,
#      before preflight, before anything is written — because it is a pure path
#      predicate, and it exists to NAME the rule that was broken: "that is the
#      private overlay, which holds owner data" is a far more useful refusal
#      than "that is not an empty directory".
#   2. An ALLOWLIST of what --force may DELETE (``overwrite_refusal``): an empty
#      directory (nothing to lose) or a directory carrying this exporter's own
#      marker file (a previous export — reproducible by definition). Everything
#      else is somebody's data, so rmtree only ever runs over a tree this tool
#      made.
#
# Neither shape is sufficient alone. A blocklist fails open on the case nobody
# enumerated: this guard used to refuse only the repo root and its ancestors, so
# ``--dest private --force`` fell straight through to rmtree on the owner's
# mounted overlay repo — the one directory AGENTS.md says an agent must never
# delete. An allowlist alone can be satisfied by an empty-looking mount point or
# by a marker file that ended up somewhere it should not be, and it cannot say
# WHICH rule a bad destination broke. So both run, blocklist first.
EXPORT_MARKER_NAME = ".jobhunt-export-marker"
EXPORT_MARKER_TEXT = (
    "This directory is an export target of automation/publish/export_public.py.\n"
    "\n"
    "The exporter writes this file right after it creates the destination, and\n"
    "treats any directory carrying it as safe to DELETE AND REPLACE on the next\n"
    "`export_public.py --dest <this directory> --force` run. It is excluded from\n"
    "the exported git history (.git/info/exclude), so it never reaches a\n"
    "published tree.\n"
    "\n"
    "Delete this file if the directory stops being a disposable export target:\n"
    "the exporter will then refuse to overwrite it.\n"
)


def _home() -> Path:
    """The user's home directory, resolved. Never raises."""
    try:
        return Path.home().resolve()
    except (RuntimeError, OSError):  # HOME unset / unresolvable
        return Path("/nonexistent-home-directory")


def _at_or_under(dest: Path, root: Path) -> bool:
    return dest == root or root in dest.parents


def _enclosing_git_repo(dest: Path) -> Path | None:
    """The nearest STRICT ancestor of ``dest`` that is a git checkout, if any.

    ``.git`` may be a directory or (in a worktree/submodule) a file, so this
    tests existence rather than ``is_dir``. Strict ancestors only: ``dest``
    itself being a git repo is handled by ``overwrite_refusal`` — a foreign
    checkout is non-empty and carries no marker — while a previous export of
    this tool has a ``.git`` of its own and must stay overwritable.
    """
    for parent in dest.parents:
        if (parent / ".git").exists():
            return parent
    return None


def owner_data_roots() -> list[tuple[Path, str]]:
    """Roots holding owner data that this exporter must never write over.

    ``private/`` under the checkout is included unconditionally and by its REAL
    path: it is the documented overlay mount, it is a separate git repository
    that may hold uncommitted work, and it is often a symlink to a tree living
    outside the checkout — in which case the "inside the source tree" rule alone
    would miss it.

    The configured roots on top of that are best-effort and additive — they
    matter when the overlay is configured to live somewhere other than
    ``private/``. A config layer that refuses to resolve contributes nothing
    rather than raising out of a safety check, and two families of root are
    dropped because a clearer rule already covers them: anything comparable to
    the checkout (a checkout with no ``config.yaml`` derives these from the
    tracked example tree, which the "inside the source checkout" rule refuses by
    a better name), and anything at or above ``$HOME`` (a pathological
    ``applications_root: ~/applications`` would otherwise refuse every
    destination under the home directory).
    """
    roots: list[tuple[Path, str]] = []
    try:
        private = (REPO_ROOT / "private").resolve()
    except OSError:
        private = REPO_ROOT / "private"
    roots.append((private, f"it is the private overlay ({private}) — a separate "
                           "repository holding owner data"))

    config = check_public._load_shared_config()
    if config is None:
        return roots
    home = _home()
    for accessor, label in (
        ("overlay_root", "the configured private overlay root"),
        ("applications_root", "the configured applications root"),
        ("companies_root", "the configured company-research root"),
        ("data_root", "the configured raw-data store root"),
    ):
        try:
            value = getattr(config, accessor)()
        except Exception:  # noqa: BLE001 — a safety check never raises
            continue
        if value is None:
            continue
        try:
            root = Path(value).resolve()
        except OSError:
            continue
        if _at_or_under(home, root):
            continue
        if _at_or_under(root, REPO_ROOT) or _at_or_under(REPO_ROOT, root):
            continue
        roots.append((root, f"it is {label} ({root}) — owner data"))
    return roots


def forbidden_destination(dest: Path) -> str | None:
    """Why ``dest`` is never a legitimate export target, or None.

    ``dest`` must already be resolved. The returned string completes the
    sentence "refusing to export into <dest>: ...", so every refusal names both
    the path and the rule it broke.
    """
    if dest == REPO_ROOT:
        return "it is the source checkout itself"
    if dest in REPO_ROOT.parents:
        return f"it contains the source checkout ({REPO_ROOT})"
    for root, why in owner_data_roots():
        if _at_or_under(dest, root):
            return why + " — agents never delete owner data"
    if REPO_ROOT in dest.parents:
        return (f"it is inside the source checkout ({REPO_ROOT}) — the export is a "
                "COPY of this tree and must land outside it")
    home = _home()
    if dest == home:
        return "it is your home directory"
    if dest in home.parents:
        return f"it contains your home directory ({home})"
    enclosing = _enclosing_git_repo(dest)
    if enclosing is not None:
        return f"it is inside another git checkout ({enclosing})"
    if dest.exists() and not dest.is_dir():
        return "it exists and is not a directory"
    return None


def overwrite_refusal(dest: Path) -> str | None:
    """Why ``--force`` may not DELETE the existing ``dest``, or None.

    The allowlist: an EMPTY directory, or a directory carrying
    ``EXPORT_MARKER_NAME``. A directory holding anything else — a foreign git
    checkout, a downloads folder, a half-remembered path — is refused, so the
    user (never this tool) decides when their own files go away.
    """
    if (dest / EXPORT_MARKER_NAME).is_file():
        return None
    try:
        entries = sorted(p.name for p in dest.iterdir())
    except OSError as exc:
        return f"it cannot be listed ({exc})"
    if not entries:
        return None
    preview = ", ".join(entries[:5]) + (", …" if len(entries) > 5 else "")
    return (f"it holds {len(entries)} entr{'y' if len(entries) == 1 else 'ies'} "
            f"({preview}) and carries no {EXPORT_MARKER_NAME}, so it is not a tree "
            "this exporter wrote")


_TOKEN_SPEC_CACHE: dict[tuple[str, ...], list] = {}


def _token_specs(tokens: list[str]) -> list:
    """Classified tokens for ``tokens``, memoised across the per-file loop.

    Classification is the GUARD's, never a second copy: an exporter that
    excluded on a different rule would either drop files the guard passes (a
    broken export) or ship files the guard fails (an export that cannot be
    published). ``_deny_reason`` runs once per tracked file, so the specs — and
    their compiled patterns — are built once per token set.
    """
    key = tuple(tokens)
    specs = _TOKEN_SPEC_CACHE.get(key)
    if specs is None:
        specs = _TOKEN_SPEC_CACHE[key] = check_public.classify_tokens(
            tokens,
            force_substring=check_public.high_specificity_tokens(),
            allowances=check_public.word_token_allowances())
    return specs


def _deny_reason(rel: str, tokens: list[str]) -> str | None:
    """Return why ``rel`` (repo-root-relative, posix) is excluded, or None.

    Applied AFTER the allowlist. Order: mechanical junk -> per-skill private notes
    -> explicit personal profiles -> personal-identity token in
    PATH -> personal-identity token in CONTENT (text files scanned line by line;
    document binaries have their extracted text/metadata scanned; the guard file
    is content-exempt).
    """
    parts = Path(rel).parts
    name = parts[-1]

    if name == ".DS_Store":
        return "junk:.DS_Store"
    if name.endswith(".pyc"):
        return "junk:*.pyc"
    if "__pycache__" in parts:
        return "junk:__pycache__"
    # Both the current folder name and its retired one — see
    # check_public.SKILL_NOTES_DIRNAMES for why the old name is never dropped.
    if any(p in check_public.SKILL_NOTES_DIRNAMES for p in parts):
        return "skill-notes"
    if rel.startswith(PROFILES_DIR + "/") and name not in PUBLIC_PROFILE_FILES:
        return "personal-profile"

    specs = _token_specs(tokens)
    hit = check_public.first_token_hit(specs, rel, rel.lower())
    if hit is not None:
        return f"token-in-path:{hit!r}"

    if rel not in TOKEN_CONTENT_EXEMPT:
        suffix = Path(rel).suffix.lower()
        if suffix in check_public.BINARY_EXTENSIONS:
            blob = check_public._binary_text(REPO_ROOT / rel, suffix)
            if blob is not None:
                hit = check_public.first_token_hit(specs, blob, blob.lower())
                if hit is not None:
                    return f"token-in-binary:{hit!r}"
        else:
            lines = check_public._read_text(REPO_ROOT / rel)
            if lines is not None:
                for lineno, line in enumerate(lines, start=1):
                    hit = check_public.first_token_hit(specs, line, line.lower())
                    if hit is not None:
                        return f"token-in-content:{hit!r}@L{lineno}"
    return None


def _copy_one(rel: str, dest_root: Path, copied: list[str],
              skipped: list[tuple[str, str]], tokens: list[str]) -> None:
    reason = _deny_reason(rel, tokens)
    if reason is not None:
        skipped.append((rel, reason))
        return
    src = REPO_ROOT / rel
    dst = dest_root / rel
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    copied.append(rel)


def tracked_files() -> list[str]:
    """Every TRACKED path in this checkout (repo-root-relative, posix, sorted).

    ``git ls-files`` — not ``os.walk`` — is the enumerator, so an untracked file
    sitting inside an allowlisted directory can never be exported. That closes
    the hole that used to ship scratch files and the owner's personal job-search
    profile symlinks (git-ignored, but on disk and inside an allowlisted tree).
    """
    proc = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "ls-files", "-z", "--cached"],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"git ls-files failed in {REPO_ROOT} (exit {proc.returncode}): "
            f"{proc.stderr.strip()}\nThe exporter enumerates TRACKED files, so it "
            "must run inside a git checkout."
        )
    return sorted(p for p in proc.stdout.split("\0") if p)


def _tracked_under(rel_dir: str, tracked: list[str]) -> list[str]:
    prefix = rel_dir.rstrip("/") + "/"
    return [p for p in tracked if p.startswith(prefix)]


def preflight(tracked: list[str]) -> list[str]:
    """Warn about every allowlisted path that would contribute nothing.

    A renamed or misspelled allowlist entry used to export zero files in total
    silence. Each of these is a warning by default and a refusal under
    ``--strict``. Run BEFORE the destination is touched so a strict refusal
    costs the caller nothing (same rule as the arming gate).
    """
    warnings: list[str] = []
    tracked_set = set(tracked)
    for rel in ALLOWLIST_FILES:
        if rel not in tracked_set:
            reason = "not tracked by git" if (REPO_ROOT / rel).exists() else "does not exist"
            warnings.append(f"allowlisted file contributes nothing: {rel} ({reason})")
    for rel_dir in allowlist_dirs():
        if not (REPO_ROOT / rel_dir).is_dir():
            warnings.append(f"allowlisted directory does not exist: {rel_dir}")
        elif not _tracked_under(rel_dir, tracked):
            warnings.append(f"allowlisted directory holds no tracked files: {rel_dir}")
    return warnings


def _copy_tree(rel_dir: str, dest_root: Path, copied: list[str],
               skipped: list[tuple[str, str]], tokens: list[str],
               tracked: list[str]) -> None:
    """Copy every TRACKED file under ``rel_dir`` (denylist applied per file).

    Symlinks are followed (``shutil.copy2``), matching the previous behaviour:
    git stores a symlink as a blob holding its target, but the export wants the
    CONTENT (e.g. the tracked ``docs/designs/CLAUDE.md -> AGENTS.md`` shim must be a
    real file in a checkout that may not support symlinks). A tracked path whose
    worktree file is missing is skipped with a reason rather than crashing.
    """
    for rel in _tracked_under(rel_dir, tracked):
        if not (REPO_ROOT / rel).exists():
            skipped.append((rel, "tracked but missing from the worktree"))
            continue
        _copy_one(rel, dest_root, copied, skipped, tokens)


def _regenerate_symlinks(dest_root: Path, skills: list[str]) -> list[str]:
    """Recreate every runtime compatibility tree for PUBLIC skills.

    Mirrors the source checkout: ``<host>/<skill> -> ../../skills/<skill>``. The
    trees are REGENERATED rather than copied, because git records a symlink as a
    blob holding its target and the source trees may also hold links for skills
    that are not part of this repo. ``skills`` comes from the SKILL.md
    frontmatter, so overlay-only skills are excluded by construction rather than
    by a hand-maintained exception.
    """
    created: list[str] = []
    for host in sync_skill_manifests.SYMLINK_HOSTS:
        base = dest_root / host
        base.mkdir(parents=True, exist_ok=True)
        for skill in skills:
            link = base / skill
            target = f"{sync_skill_manifests.SYMLINK_TARGET_PREFIX}{skill}"
            if link.is_symlink() or link.exists():
                link.unlink()
            os.symlink(target, link)
            created.append(f"{host}/{skill} -> {target}")
    return created


def _run_guard(dest_root: Path, tokens: list[str]) -> int:
    """git init + add -A in <dest>, then run the leak guard against the copied tree.

    The guard enumerates TRACKED files, so we initialize a repo + stage everything
    first (independent of whether we will commit). The freshly copied tree has no
    ``config.yaml`` of its own, so we forward the resolved REAL token set via
    ``JOBHUNT_PERSONAL_TOKENS`` — otherwise the guard (falling back to the fictional
    example identity) would screen against no real tokens. Returns the guard's exit
    code (0 = clean).
    """
    subprocess.run(["git", "init"], cwd=dest_root, check=True, capture_output=True, text=True)
    # Keep the export marker out of the exported HISTORY. It is a local property
    # of this directory ("a later --force run may replace me"), not content a
    # published repo should carry, so it goes in .git/info/exclude — which is
    # repository-local and never published — rather than the shipped .gitignore.
    exclude = dest_root / ".git" / "info" / "exclude"
    exclude.parent.mkdir(parents=True, exist_ok=True)
    with exclude.open("a", encoding="utf-8") as handle:
        handle.write(f"\n# written by export_public.py; see {EXPORT_MARKER_NAME}\n"
                     f"/{EXPORT_MARKER_NAME}\n")
    subprocess.run(["git", "add", "-A"], cwd=dest_root, check=True, capture_output=True, text=True)

    env = dict(os.environ)
    env[check_public.TOKENS_ENV_VAR] = "\n".join(tokens)
    # Never forward an ABSOLUTE $JOBHUNT_CONFIG into a subprocess whose cwd is a
    # DIFFERENT tree. It would point the guard's config discovery back at THIS
    # checkout while everything else it resolves — including its own
    # config.example.yaml — lives in the export, and a config that belongs to
    # another tree is not this tree's config. The guard needs no config here: the
    # real token set is forwarded explicitly above, which is exactly how CI arms
    # it. Dropping the var lets discovery fall back to the export's own
    # config.example.yaml, so the fictional persona contributes nothing.
    shared_config = check_public._load_shared_config()
    env.pop(getattr(shared_config, "ENV_VAR", "JOBHUNT_CONFIG"), None)
    # Keep the freshly copied tree byte-for-byte what the allowlist produced: the
    # guard imports sibling/shared modules, and CPython would otherwise leave
    # __pycache__/*.pyc behind INSIDE the export (git-ignored, so invisible to the
    # guard's tracked-file scan, but still not something an export should carry).
    env["PYTHONDONTWRITEBYTECODE"] = "1"

    print("\n=== Leak guard (check_public.py) ===")
    guard = subprocess.run(
        [sys.executable, "automation/publish/check_public.py"],
        cwd=dest_root,
        capture_output=True,
        text=True,
        env=env,
    )
    if guard.stdout:
        print(guard.stdout, end="" if guard.stdout.endswith("\n") else "\n")
    if guard.stderr:
        print(guard.stderr, end="", file=sys.stderr)
    return guard.returncode


def _commit(dest_root: Path) -> int:
    """Commit the (already staged) export. Returns the git exit code."""
    commit = subprocess.run(
        ["git", "commit", "-m", "Initial public release of the job-hunting toolkit"],
        cwd=dest_root,
        capture_output=True,
        text=True,
    )
    if commit.stdout:
        print(commit.stdout, end="" if commit.stdout.endswith("\n") else "\n")
    if commit.returncode != 0:
        if commit.stderr:
            print(commit.stderr, end="", file=sys.stderr)
        print(f"git commit failed (exit {commit.returncode}).")
    return commit.returncode


def _print_manifest(dest_root: Path, copied: list[str], skipped: list[tuple[str, str]],
                    symlinks: list[str]) -> None:
    top_level = sorted(p.name for p in dest_root.iterdir())
    print("=== Public export manifest ===")
    print(f"  destination:   {dest_root}")
    print(f"  files copied:  {len(copied)}")
    print(f"  files skipped: {len(skipped)} (denylist)")
    print(f"  symlinks:      {len(symlinks)}")
    print(f"  top-level entries ({len(top_level)}):")
    for name in top_level:
        marker = "/" if (dest_root / name).is_dir() and not (dest_root / name).is_symlink() else ""
        print(f"    - {name}{marker}")
    if skipped:
        print("  skipped (denylist):")
        for rel, reason in skipped:
            print(f"    - {rel}  [{reason}]")


def export(dest: Path, git_init: bool, force: bool, strict: bool = False) -> int:
    # Where the destination is decided. This runs before EVERY other gate: it is
    # a pure path predicate (no writes, no subprocesses, no config required), so
    # the most destructive mistake available — pointing --force at the overlay,
    # the checkout, or your home directory — is refused even in a checkout that
    # would fail the arming gate a few lines below.
    dest = dest.resolve()
    reason = forbidden_destination(dest)
    if reason is not None:
        print(f"error: refusing to export into {dest}:\n"
              f"       {reason}.\n"
              "       Choose a destination OUTSIDE this checkout — a path that does not\n"
              "       exist yet, or an empty directory (`mktemp -d`). --force deletes only\n"
              f"       an empty directory or one carrying {EXPORT_MARKER_NAME}.",
              file=sys.stderr)
        return 2

    # Refuse to export from an UNARMED checkout. Still ahead of everything that
    # touches the filesystem — above all the --force delete — so a refusal costs
    # the caller nothing.
    #
    # The guard we run against the copied tree is armed through
    # ``JOBHUNT_PERSONAL_TOKENS``, which we set from the UNION below. A checkout
    # holding private/leak_tokens.txt but no real config.yaml therefore forwards a
    # NON-EMPTY set, so that guard run would look armed while knowing none of the
    # owner's name, email, or handles — the export's final gate would pass without
    # ever screening for the identity. Gate on the identity set, exactly as
    # ``check_public.main`` does.
    if not check_public.identity_tokens():
        print("error: refusing to export — the leak guard is UNARMED in this checkout.\n"
              "       Zero identity tokens resolved, so the export's final guard run would\n"
              "       screen against no real identity and report the tree safe to publish.",
              file=sys.stderr)
        for line in check_public.unarmed_report():
            print(line, file=sys.stderr)
        print("       Export only from a maintainer checkout whose config.yaml carries the\n"
              f"       real candidate identity, or set ${check_public.TOKENS_ENV_VAR}.",
              file=sys.stderr)
        return 2

    # Enumerate TRACKED files once, then report every allowlist entry that
    # contributes nothing — also BEFORE --force deletes the destination, so a
    # --strict refusal costs the caller nothing.
    tracked = tracked_files()
    warnings = preflight(tracked)
    for warning in warnings:
        print(f"warning: {warning}", file=sys.stderr)
    if warnings and strict:
        print(f"error: refusing to export — {len(warnings)} allowlist warning(s) "
              "under --strict.\n"
              "       Fix or remove the allowlist entries above, or drop --strict.",
              file=sys.stderr)
        return 2

    if dest.exists():
        if not force:
            print(f"error: destination exists: {dest}\n"
                  "       pass --force to overwrite it.", file=sys.stderr)
            return 2
        blocked = overwrite_refusal(dest)
        if blocked is not None:
            print(f"error: refusing to delete {dest}:\n"
                  f"       {blocked}.\n"
                  "       Export to a new directory, or delete this one yourself first —\n"
                  "       this tool removes only empty directories and its own exports.",
                  file=sys.stderr)
            return 2
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    # Written BEFORE the copy, so an export that dies halfway (a leak-guard
    # failure, a Ctrl-C) still leaves a destination that the next --force run can
    # replace. ``_run_guard`` keeps it out of the exported git history.
    (dest / EXPORT_MARKER_NAME).write_text(EXPORT_MARKER_TEXT, encoding="utf-8")

    # Resolve the REAL personal-identity tokens once (from the source checkout's
    # config.yaml + private/leak_tokens.txt); used for the copy-time denylist AND
    # forwarded to the guard run against the copied tree.
    tokens = check_public.personal_tokens()

    copied: list[str] = []
    skipped: list[tuple[str, str]] = []
    tracked_set = set(tracked)

    for rel in ALLOWLIST_FILES:
        if rel in tracked_set and (REPO_ROOT / rel).is_file():
            _copy_one(rel, dest, copied, skipped, tokens)
    for rel_dir in allowlist_dirs():
        _copy_tree(rel_dir, dest, copied, skipped, tokens, tracked)

    (dest / ".gitignore").write_text(
        (REPO_ROOT / GITIGNORE_REL).read_text(encoding="utf-8"), encoding="utf-8")

    skills = public_skills()
    symlinks = _regenerate_symlinks(dest, skills)

    _print_manifest(dest, copied, skipped, symlinks)
    print(f"  public skills: {len(skills)} (skills/*/SKILL.md `visibility: public`)")
    print(f"  active tokens: {len(tokens)} (from config identity + overlay + env)")

    # The leak guard ALWAYS runs against the copied tree (it is the final gate) —
    # git_init only controls whether we also commit the clean export.
    rc = _run_guard(dest, tokens)
    if rc != 0:
        print("\nLEAK GUARD FAILED (exit "
              f"{rc}) — export NOT committed. Fix the violations above (genericize "
              "the offending file, move personal content into the overlay's "
              "skill-notes/ folder, or extend the token list) and re-run.")
        return rc

    print("Leak guard PASSED.")
    if not git_init:
        print("export committed: no (re-run with --git-init to commit the clean export)")
        return 0
    return _commit(dest)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--dest", required=True, help="destination directory for the public export")
    parser.add_argument("--git-init", action="store_true",
                        help="git init + add -A, run the leak guard, and commit only if it passes")
    parser.add_argument("--force", action="store_true",
                        help="overwrite --dest if it already exists — only when it is "
                             "EMPTY or is a previous export of this tool (it carries "
                             f"{EXPORT_MARKER_NAME}); never the checkout, the private "
                             "overlay, your home directory, or another git checkout")
    parser.add_argument("--strict", action="store_true",
                        help="refuse to export when any allowlisted path contributes "
                             "nothing (missing directory, untracked/absent file)")
    args = parser.parse_args(argv)
    return export(Path(args.dest), args.git_init, args.force, args.strict)


if __name__ == "__main__":
    raise SystemExit(main())
