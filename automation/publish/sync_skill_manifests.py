#!/usr/bin/env python3
"""Derive every skill-visibility manifest from ``skills/*/SKILL.md`` frontmatter.

``visibility: public|private`` in a skill's own ``SKILL.md`` is the SINGLE SOURCE
OF TRUTH for whether that skill ships. Four downstream surfaces used to repeat
that answer by hand and drifted apart (a skill that existed had never shipped in
any export and was not installable as a plugin):

  * ``automation/publish/export_public.py`` — which ``skills/<name>`` trees the
    allowlist exporter copies, and which compat symlinks it regenerates;
  * ``.claude-plugin/marketplace.json`` — the plugin manifest (one entry per
    public skill, ``description`` taken from the same frontmatter so the blurb
    cannot drift either);
  * ``.agents/skills/<name>``, ``.claude/skills/<name>``, and
    ``.cursor/skills/<name>`` — the runtime compat symlink trees,
    ``<host>/<skill> -> ../../skills/<skill>``.

This module is the ONE implementation everything reads: the exporter imports
``public_skills()``, the reconciler imports ``findings()`` (check
``skill-manifests``), and ``check_public.parse_frontmatter_visibility()``
delegates to ``parse_frontmatter()`` here, so there is exactly one frontmatter
parser in the repo. Stdlib only, no repo-root imports — it must run inside a
freshly exported checkout.

Ordering rule for ``marketplace.json``: existing entries keep their current
order (the file is human-curated and a wholesale reorder makes the diff
unreviewable); newly-public skills are appended in alphabetical order. Entries
for skills that are no longer public are dropped.

The symlink trees are managed PER SKILL, and ownership is decided by WHERE A LINK
POINTS, never by its name. This tool owns exactly the links into
``../../skills/`` — the tracked, PUBLIC ones. Two other kinds of entry share the
same directories and are neither reported nor touched:

  * a PRIVATE skill's runtime link, ``-> ../../private/skills/<name>``, created by
    ``automation/bootstrap_overlay.py`` and git-ignored. Since workspace-restructure
    phase 4 this is how a private skill reaches the runtime: nothing private is
    placed under ``skills/`` any more, so ``read_skills()`` sees only public
    skills and this generator must not treat the overlay entry as drift and
    delete it (that would silently uninstall the owner's private skills on every
    reconciler-driven sync);
  * a third-party skill installed into the same host directory by some other tool.

Usage:
    # Regenerate marketplace.json + all runtime adapter trees from the frontmatter
    .venv/bin/python automation/publish/sync_skill_manifests.py

    # Verify only — exit 1 if any manifest drifted (the reconciler runs this
    # logic in-process as the `skill-manifests` check)
    .venv/bin/python automation/publish/sync_skill_manifests.py --check
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

# automation/publish/sync_skill_manifests.py -> repo root is two parents up.
REPO_ROOT = Path(__file__).resolve().parents[2]

# Where skills live, and the manifests derived from their frontmatter.
SKILLS_DIRNAME = "skills"
MARKETPLACE_REL = ".claude-plugin/marketplace.json"

# ``<host>/<skill> -> ../../skills/<skill>``. A host is skipped entirely when its
# top-level directory is absent, so an agent-specific tree can simply not exist.
SYMLINK_HOSTS = (".agents/skills", ".claude/skills", ".cursor/skills")
SYMLINK_TARGET_PREFIX = "../../skills/"

# A PRIVATE skill's runtime link in the same host dirs, written by
# ``automation/bootstrap_overlay.py``. Named here only so the ownership boundary
# is documented in the one module that enumerates those directories; the code
# needs no special case, because a target under this prefix does not start with
# ``SYMLINK_TARGET_PREFIX`` and is therefore already unmanaged (see
# ``_managed_links``). It is asserted by
# ``automation/publish/tests/test_skill_manifests.py``.
PRIVATE_SKILL_TARGET_PREFIX = "../../private/skills/"

PUBLIC = "public"
PRIVATE = "private"


@dataclass(frozen=True)
class SkillDecl:
    """One ``skills/<name>/SKILL.md`` and what its frontmatter declares."""
    name: str
    visibility: str | None
    description: str
    skill_md: Path


def parse_frontmatter(md_path: Path) -> dict[str, str]:
    """Return the YAML frontmatter of ``md_path`` as a flat ``key -> value`` map.

    Reads only the block between the leading ``---`` fences and only simple
    ``key: value`` lines (every SKILL.md frontmatter in this repo is exactly
    that shape). Values are stripped of surrounding quotes. Returns ``{}`` when
    the file is unreadable or has no frontmatter.
    """
    try:
        text = md_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return {}
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    fields: dict[str, str] = {}
    for line in lines[1:]:
        if line.strip() == "---":
            break
        key, sep, value = line.partition(":")
        if not sep or line[:1] in (" ", "\t", "-"):
            continue
        fields[key.strip()] = value.strip().strip("'\"")
    return fields


def frontmatter_visibility(md_path: Path) -> str | None:
    """The lowercased ``visibility`` value of a SKILL.md, or None when absent."""
    return (parse_frontmatter(md_path).get("visibility") or "").lower() or None


def read_skills(repo_root: Path = REPO_ROOT) -> list[SkillDecl]:
    """Every ``skills/*/SKILL.md`` declaration, sorted by skill name."""
    skills_root = Path(repo_root) / SKILLS_DIRNAME
    if not skills_root.is_dir():
        return []
    decls: list[SkillDecl] = []
    for skill_md in sorted(skills_root.glob("*/SKILL.md")):
        fields = parse_frontmatter(skill_md)
        decls.append(SkillDecl(
            name=skill_md.parent.name,
            visibility=(fields.get("visibility") or "").lower() or None,
            description=fields.get("description", ""),
            skill_md=skill_md,
        ))
    return decls


def public_skills(repo_root: Path = REPO_ROOT) -> list[str]:
    """Names of the skills whose frontmatter declares ``visibility: public``."""
    return [d.name for d in read_skills(repo_root) if d.visibility == PUBLIC]


def private_skills(repo_root: Path = REPO_ROOT) -> list[str]:
    """Names of the skills whose frontmatter declares ``visibility: private``."""
    return [d.name for d in read_skills(repo_root) if d.visibility == PRIVATE]


def _visibility_findings(repo_root: Path) -> list[tuple[str, str]]:
    """A SKILL.md must declare a visibility this module understands."""
    out: list[tuple[str, str]] = []
    for decl in read_skills(repo_root):
        rel = decl.skill_md.relative_to(repo_root).as_posix()
        if decl.visibility is None:
            out.append((rel, "frontmatter declares no `visibility:` key "
                             "(the single source of truth for whether the skill ships)"))
        elif decl.visibility not in (PUBLIC, PRIVATE):
            out.append((rel, f"unknown visibility {decl.visibility!r} "
                             f"(expected {PUBLIC!r} or {PRIVATE!r})"))
        elif decl.visibility == PUBLIC and not decl.description:
            out.append((rel, "frontmatter declares no `description:` key "
                             "(marketplace.json derives the plugin blurb from it)"))
    return out


# ── marketplace.json ─────────────────────────────────────────────────────────

def _plugin_entries(repo_root: Path, existing: list) -> list[dict]:
    """Plugin entries for every public skill, preserving the existing order."""
    decls = {d.name: d for d in read_skills(repo_root)}
    public = public_skills(repo_root)
    kept = [e.get("name") for e in existing if isinstance(e, dict)]
    ordered = [n for n in kept if n in public]
    ordered += sorted(n for n in public if n not in ordered)
    return [
        {
            "name": name,
            "source": f"./{SKILLS_DIRNAME}/{name}",
            "description": decls[name].description,
        }
        for name in ordered
    ]


def render_marketplace(repo_root: Path = REPO_ROOT) -> str | None:
    """The marketplace.json text derived from frontmatter, or None if absent.

    The envelope (``name`` / ``owner`` / ``metadata`` and their key order) is
    read back from the existing file and re-emitted unchanged; only ``plugins``
    is regenerated. Returns None when there is no file to derive an envelope
    from — that case is reported as a finding, never silently invented.
    """
    path = Path(repo_root) / MARKETPLACE_REL
    if not path.is_file():
        return None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(doc, dict):
        return None
    existing = doc.get("plugins")
    doc["plugins"] = _plugin_entries(repo_root, existing if isinstance(existing, list) else [])
    return json.dumps(doc, indent=2, ensure_ascii=False) + "\n"


def marketplace_findings(repo_root: Path = REPO_ROOT) -> list[tuple[str, str]]:
    """Drift between ``.claude-plugin/marketplace.json`` and the frontmatter."""
    root = Path(repo_root)
    plugin_dir = root / MARKETPLACE_REL
    if not plugin_dir.parent.is_dir():
        return []  # the whole surface is absent — nothing to reconcile
    if not plugin_dir.is_file():
        return [(MARKETPLACE_REL, "missing — run "
                                  "automation/publish/sync_skill_manifests.py")]
    expected = render_marketplace(root)
    if expected is None:
        return [(MARKETPLACE_REL, "unreadable or not a JSON object")]
    if plugin_dir.read_text(encoding="utf-8") != expected:
        return [(MARKETPLACE_REL,
                 "stale — plugin entries do not match skills/*/SKILL.md frontmatter; "
                 "run automation/publish/sync_skill_manifests.py")]
    return []


# ── Runtime skill-adapter symlink trees ─────────────────────────────────────

def _managed_links(host_dir: Path) -> dict[str, str]:
    """Entries under ``host_dir`` this tool owns: symlinks into ``../../skills/``.

    An entry that is not a symlink, or a symlink pointing somewhere else, belongs
    to someone else and is never touched or reported — a third-party skill
    installed into the same host directory, or a PRIVATE skill's git-ignored
    runtime link into ``PRIVATE_SKILL_TARGET_PREFIX``. Ownership is decided by the
    TARGET, so a private skill and a public one can even share a name without
    either tool fighting the other.
    """
    managed: dict[str, str] = {}
    if not host_dir.is_dir():
        return managed
    for entry in sorted(host_dir.iterdir()):
        if not entry.is_symlink():
            continue
        target = os.readlink(entry)
        if target.startswith(SYMLINK_TARGET_PREFIX):
            managed[entry.name] = target
    return managed


def _active_hosts(repo_root: Path) -> list[Path]:
    """Host dirs whose agent-specific root exists."""
    root = Path(repo_root)
    return [root / host for host in SYMLINK_HOSTS if (root / host).parent.is_dir()]


def symlink_findings(repo_root: Path = REPO_ROOT) -> list[tuple[str, str]]:
    """Drift between the compat symlink trees and the frontmatter."""
    root = Path(repo_root)
    public = public_skills(root)
    out: list[tuple[str, str]] = []
    for host_dir in _active_hosts(root):
        host = host_dir.relative_to(root).as_posix()
        managed = _managed_links(host_dir)
        for name in public:
            want = f"{SYMLINK_TARGET_PREFIX}{name}"
            rel = f"{host}/{name}"
            if name not in managed:
                out.append((rel, f"missing symlink -> {want} for public skill "
                                 f"{name!r} (skills/{name}/SKILL.md says visibility: public)"))
            elif managed[name] != want:
                out.append((rel, f"symlink points at {managed[name]!r}, expected {want!r}"))
        for name, target in managed.items():
            if name not in public:
                out.append((f"{host}/{name}",
                            f"symlink -> {target} for a skill that is not public "
                            f"(no skills/{name}/SKILL.md with visibility: public)"))
    return out


# ── combined API ─────────────────────────────────────────────────────────────

def findings(repo_root: Path = REPO_ROOT) -> list[tuple[str, str]]:
    """Every manifest disagreement with the SKILL.md frontmatter.

    Returns ``(repo-relative subject, message)`` pairs. Empty when the
    ``skills/`` root is absent, so a tree without skills is a no-op.
    """
    root = Path(repo_root)
    if not (root / SKILLS_DIRNAME).is_dir():
        return []
    return (_visibility_findings(root)
            + marketplace_findings(root)
            + symlink_findings(root))


def sync(repo_root: Path = REPO_ROOT) -> list[str]:
    """Rewrite every derived manifest from the frontmatter. Returns the actions."""
    root = Path(repo_root)
    actions: list[str] = []

    expected = render_marketplace(root)
    path = root / MARKETPLACE_REL
    if expected is None:
        if path.parent.is_dir():
            actions.append(f"SKIP {MARKETPLACE_REL} (missing or unreadable; "
                           "its envelope is hand-owned and never invented)")
    elif path.read_text(encoding="utf-8") != expected:
        path.write_text(expected, encoding="utf-8")
        actions.append(f"wrote {MARKETPLACE_REL} "
                       f"({len(json.loads(expected)['plugins'])} plugin entries)")

    public = public_skills(root)
    for host in SYMLINK_HOSTS:
        host_dir = root / host
        if not host_dir.parent.is_dir():
            continue
        host_dir.mkdir(parents=True, exist_ok=True)
        managed = _managed_links(host_dir)
        for name in public:
            want = f"{SYMLINK_TARGET_PREFIX}{name}"
            link = host_dir / name
            if managed.get(name) == want:
                continue
            if link.is_symlink() or link.exists():
                link.unlink()
            os.symlink(want, link)
            actions.append(f"linked {host}/{name} -> {want}")
        for name in managed:
            if name not in public:
                (host_dir / name).unlink()
                actions.append(f"removed {host}/{name} (not a public skill)")
    return actions


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true",
                        help="verify only — exit 1 if any manifest drifted")
    args = parser.parse_args(argv)

    if args.check:
        found = findings(REPO_ROOT)
        if found:
            print(f"skill manifests OUT OF SYNC: {len(found)} finding(s)", file=sys.stderr)
            for subject, message in found:
                print(f"  {subject}: {message}", file=sys.stderr)
            print("Run: .venv/bin/python automation/publish/sync_skill_manifests.py",
                  file=sys.stderr)
            return 1
        public = public_skills(REPO_ROOT)
        print(f"skill manifests in sync ({len(public)} public skill(s): "
              f"{', '.join(public)})")
        return 0

    actions = sync(REPO_ROOT)
    for action in actions:
        print(action)
    if not actions:
        print("skill manifests already in sync")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
