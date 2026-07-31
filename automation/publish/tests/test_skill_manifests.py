"""Tests for the skill-visibility single source of truth.

``skills/<name>/SKILL.md`` frontmatter (``visibility: public|private``) is the ONE
declaration of whether a skill ships. Five surfaces are derived from it — the
exporter's public-skill list, ``.claude-plugin/marketplace.json``, and the Codex,
Claude Code, and Cursor compat symlink trees — and they used to be hand-maintained
copies that drifted (``search-recall-audit`` existed but had never shipped in any
export and was not installable as a plugin).

These tests work on a SYNTHETIC tree so flipping a visibility is possible without
touching the real repo, plus a handful of assertions against the live tree so the
real manifests cannot silently drift either.

Run with:
    .venv/bin/python -m unittest discover automation/publish/tests
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

# Make the sibling modules importable (automation/publish/).
_PUBLISH_DIR = Path(__file__).resolve().parents[1]
if str(_PUBLISH_DIR) not in sys.path:
    sys.path.insert(0, str(_PUBLISH_DIR))

import check_public  # noqa: E402
import export_public  # noqa: E402
import sync_skill_manifests as ssm  # noqa: E402

REPO_ROOT = check_public.REPO_ROOT

# The reconciler lives in a sibling automation package; import it the same way.
_RECONCILE_DIR = REPO_ROOT / "automation" / "reconcile"
if str(_RECONCILE_DIR) not in sys.path:
    sys.path.insert(0, str(_RECONCILE_DIR))

import reconcile  # noqa: E402


def _skill(root: Path, name: str, visibility: str, description: str = "Does a thing.") -> None:
    d = root / "skills" / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(
        f"---\nname: {name}\nvisibility: {visibility}\ndescription: {description}\n---\n\n"
        f"# {name}\n",
        encoding="utf-8",
    )


def _marketplace(root: Path, plugin_names: list[str]) -> None:
    (root / ".claude-plugin").mkdir(parents=True, exist_ok=True)
    doc = {
        "name": "job-hunting-toolkit",
        "owner": {"name": "Jobs Finder Toolkit"},
        "metadata": {"description": "Example marketplace."},
        "plugins": [
            {"name": n, "source": f"./skills/{n}", "description": "Does a thing."}
            for n in plugin_names
        ],
    }
    (root / ".claude-plugin/marketplace.json").write_text(
        json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _symlinks(root: Path, names: list[str]) -> None:
    for host in ssm.SYMLINK_HOSTS:
        d = root / host
        d.mkdir(parents=True, exist_ok=True)
        for n in names:
            os.symlink(f"{ssm.SYMLINK_TARGET_PREFIX}{n}", d / n)


def _fixture(root: Path) -> None:
    """A tiny tree whose manifests agree with its frontmatter."""
    _skill(root, "alpha", "public")
    _skill(root, "beta", "public")
    _skill(root, "secret", "private")
    _marketplace(root, ["alpha", "beta"])
    _symlinks(root, ["alpha", "beta"])
    ssm.sync(root)  # normalize formatting so the fixture starts clean


class SyntheticVisibilityTests(unittest.TestCase):
    """A visibility flip must move every derived surface, and be REPORTED."""

    def test_fixture_starts_in_sync(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _fixture(root)
            self.assertEqual(ssm.public_skills(root), ["alpha", "beta"])
            self.assertEqual(ssm.private_skills(root), ["secret"])
            self.assertEqual(ssm.findings(root), [])

    def test_flipping_visibility_changes_the_derived_lists(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _fixture(root)
            _skill(root, "beta", "private")  # rewrite the frontmatter only

            self.assertEqual(ssm.public_skills(root), ["alpha"])
            self.assertIn("beta", ssm.private_skills(root))

            found = dict(ssm.findings(root))
            self.assertIn(ssm.MARKETPLACE_REL, found)
            self.assertIn("stale", found[ssm.MARKETPLACE_REL])
            for host in ssm.SYMLINK_HOSTS:
                self.assertIn(f"{host}/beta", found)

            # ...and the writer removes the surfaces the flip invalidated.
            ssm.sync(root)
            self.assertEqual(ssm.findings(root), [])
            doc = json.loads((root / ssm.MARKETPLACE_REL).read_text(encoding="utf-8"))
            self.assertEqual([p["name"] for p in doc["plugins"]], ["alpha"])
            for host in ssm.SYMLINK_HOSTS:
                self.assertFalse((root / host / "beta").is_symlink())

    def test_flipping_visibility_to_public_adds_every_surface(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _fixture(root)
            _skill(root, "secret", "public")  # the private skill goes public

            self.assertEqual(ssm.public_skills(root), ["alpha", "beta", "secret"])
            found = dict(ssm.findings(root))
            self.assertIn(ssm.MARKETPLACE_REL, found)
            for host in ssm.SYMLINK_HOSTS:
                self.assertIn(f"{host}/secret", found)
                self.assertIn("missing symlink", found[f"{host}/secret"])

            ssm.sync(root)
            self.assertEqual(ssm.findings(root), [])
            doc = json.loads((root / ssm.MARKETPLACE_REL).read_text(encoding="utf-8"))
            # Appended (alphabetically) after the curated existing order.
            self.assertEqual([p["name"] for p in doc["plugins"]],
                             ["alpha", "beta", "secret"])

    def test_stale_marketplace_alone_is_a_finding(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _fixture(root)
            _marketplace(root, ["alpha"])  # drop beta by hand; frontmatter unchanged
            found = dict(ssm.findings(root))
            self.assertIn(ssm.MARKETPLACE_REL, found)

    def test_stale_symlink_tree_alone_is_a_finding(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _fixture(root)
            (root / ".claude/skills/beta").unlink()
            found = dict(ssm.findings(root))
            self.assertIn(".claude/skills/beta", found)
            self.assertNotIn(".cursor/skills/beta", found)

    def test_symlink_into_the_public_tree_for_a_private_skill_is_a_finding(self):
        """``-> ../../skills/<name>`` is OURS, so a non-public name there is drift."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _fixture(root)
            os.symlink(f"{ssm.SYMLINK_TARGET_PREFIX}secret", root / ".claude/skills/secret")
            found = dict(ssm.findings(root))
            self.assertIn(".claude/skills/secret", found)
            self.assertIn("not public", found[".claude/skills/secret"])

    def test_private_skill_runtime_link_is_tolerated_and_preserved(self):
        """A private skill's ``-> ../../private/skills/<name>`` entry is NOT ours.

        Since workspace-restructure phase 4 the private skills live only in
        ``private/skills/`` and reach the runtime through a git-ignored entry in
        these same host directories, written by ``bootstrap_overlay.py``. This
        generator sees no ``skills/<name>/SKILL.md`` for them, so if it claimed
        every entry by NAME it would report each one as drift and then delete it
        — silently uninstalling the owner's private skills on every sync. It
        claims by TARGET instead, so the entry is neither reported nor touched.
        """
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _fixture(root)
            (root / "private/skills/hidden").mkdir(parents=True)
            for host in ssm.SYMLINK_HOSTS:
                os.symlink(f"{ssm.PRIVATE_SKILL_TARGET_PREFIX}hidden",
                           root / host / "hidden")

            # No SKILL.md under skills/ for it: invisible to the frontmatter scan.
            self.assertNotIn("hidden", ssm.public_skills(root))
            self.assertNotIn("hidden", ssm.private_skills(root))
            # Tolerated...
            self.assertEqual(ssm.findings(root), [])
            # ...and preserved, still pointing into the overlay.
            self.assertEqual(ssm.sync(root), [])
            for host in ssm.SYMLINK_HOSTS:
                link = root / host / "hidden"
                self.assertTrue(link.is_symlink())
                self.assertEqual(os.readlink(link),
                                 f"{ssm.PRIVATE_SKILL_TARGET_PREFIX}hidden")

    def test_foreign_symlink_and_directory_are_left_alone(self):
        """A third-party skill installed into the same host dir is not ours.

        The plain directory is deliberate: a renamed-away skill leaves one behind
        (`.cursor/skills/github-manager` outlived the github-manager ->
        github-workflow rename), and so does any tool that installs a real skill
        folder rather than a symlink. Ownership is decided by TARGET, so neither
        is reported or touched. The fixture name is kept unambiguously foreign so
        nobody reads this test as blessing one of our own leftovers.
        """
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _fixture(root)
            (root / ".cursor/skills/some-other-tools-skill").mkdir()
            os.symlink("../../elsewhere/thing", root / ".cursor/skills/thing")

            self.assertEqual(ssm.findings(root), [])
            ssm.sync(root)
            self.assertTrue((root / ".cursor/skills/some-other-tools-skill").is_dir())
            self.assertTrue((root / ".cursor/skills/thing").is_symlink())

    def test_missing_visibility_key_is_a_finding_and_never_public(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _fixture(root)
            (root / "skills/gamma").mkdir(parents=True)
            (root / "skills/gamma/SKILL.md").write_text(
                "---\nname: gamma\ndescription: No visibility key.\n---\n", encoding="utf-8")
            self.assertNotIn("gamma", ssm.public_skills(root))
            found = dict(ssm.findings(root))
            self.assertIn("skills/gamma/SKILL.md", found)
            self.assertIn("visibility", found["skills/gamma/SKILL.md"])

    def test_sync_is_idempotent(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _fixture(root)
            _skill(root, "secret", "public")
            ssm.sync(root)
            before = (root / ssm.MARKETPLACE_REL).read_text(encoding="utf-8")
            self.assertEqual(ssm.sync(root), [])
            self.assertEqual((root / ssm.MARKETPLACE_REL).read_text(encoding="utf-8"), before)

    def test_marketplace_envelope_is_preserved(self):
        """Only ``plugins`` is regenerated; the hand-owned envelope survives."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _fixture(root)
            path = root / ssm.MARKETPLACE_REL
            doc = json.loads(path.read_text(encoding="utf-8"))
            doc["owner"] = {"name": "Someone", "url": "https://example.com"}
            path.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n",
                            encoding="utf-8")
            _skill(root, "secret", "public")
            ssm.sync(root)
            after = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(list(after.keys()), ["name", "owner", "metadata", "plugins"])
            self.assertEqual(after["owner"], {"name": "Someone", "url": "https://example.com"})

    def test_marketplace_description_comes_from_frontmatter(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _fixture(root)
            _skill(root, "alpha", "public", description="A brand new blurb.")
            self.assertIn(ssm.MARKETPLACE_REL, dict(ssm.findings(root)))
            ssm.sync(root)
            doc = json.loads((root / ssm.MARKETPLACE_REL).read_text(encoding="utf-8"))
            entry = next(p for p in doc["plugins"] if p["name"] == "alpha")
            self.assertEqual(entry["description"], "A brand new blurb.")

    def test_no_skills_root_is_a_no_op(self):
        """Mirrors the reconciler contract: a check no-ops when its folder is absent."""
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(ssm.findings(Path(td)), [])


class ReconcilerCheckTests(unittest.TestCase):
    """The reconciler must FAIL when a derived manifest drifts."""

    def _with_root(self, root: Path):
        original = reconcile.REPO_ROOT
        reconcile.REPO_ROOT = root
        self.addCleanup(lambda: setattr(reconcile, "REPO_ROOT", original))

    def test_check_is_registered(self):
        self.assertIn("skill-manifests", reconcile.CHECKS)

    def test_clean_tree_yields_no_findings(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _fixture(root)
            self._with_root(root)
            self.assertEqual(reconcile.check_skill_manifests(), [])

    def test_stale_manifest_fails_the_reconciler(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _fixture(root)
            _skill(root, "beta", "private")
            self._with_root(root)
            findings = reconcile.check_skill_manifests()
            self.assertTrue(findings)
            self.assertTrue(all(f.check == "skill-manifests" for f in findings))
            subjects = {f.subject for f in findings}
            self.assertIn(ssm.MARKETPLACE_REL, subjects)

    def test_missing_skills_root_no_ops(self):
        """The documented missing-root no-op: an export subset must still pass."""
        with tempfile.TemporaryDirectory() as td:
            self._with_root(Path(td))
            self.assertEqual(reconcile.check_skill_manifests(), [])


class LiveTreeTests(unittest.TestCase):
    """The real repo's manifests must agree with the real frontmatter."""

    def test_repo_manifests_are_in_sync(self):
        self.assertEqual(ssm.findings(REPO_ROOT), [])

    def test_search_recall_audit_is_public(self):
        # The concrete regression: it existed but shipped nowhere.
        self.assertIn("search-recall-audit", ssm.public_skills(REPO_ROOT))
        doc = json.loads((REPO_ROOT / ssm.MARKETPLACE_REL).read_text(encoding="utf-8"))
        self.assertIn("search-recall-audit", [p["name"] for p in doc["plugins"]])

    def test_no_skill_under_skills_is_private(self):
        """Phase 4 invariant: nothing under ``skills/`` is private any more.

        This replaces an assertion that read the private skills THROUGH the
        deleted overlay symlinks and skipped itself when the overlay was absent.
        Those symlinks put overlay content at a public-looking path, which is
        exactly what phase 4 removed, so the strictly stronger statement now
        holds in every checkout: ``skills/`` is entirely public.
        ``check_public.find_private_skill_violations`` stays armed for the case
        a private skill is ever put back there.
        """
        self.assertEqual(ssm.private_skills(REPO_ROOT), [])

    def test_private_skills_reach_the_runtime_from_the_overlay(self):
        """With the overlay mounted, each private skill is linked from the hosts.

        The link points STRAIGHT at ``private/skills/<name>`` — no public-tree hop
        — and is git-ignored, so the runtime lists it while the public index
        never can. Written by ``automation/bootstrap_overlay.py``.
        """
        overlay_skills = REPO_ROOT / "private" / "skills"
        if not overlay_skills.is_dir():
            self.skipTest("private overlay not mounted")
        names = sorted(p.name for p in overlay_skills.iterdir()
                       if p.is_dir() and (p / "SKILL.md").is_file())
        self.assertTrue(names, "overlay holds no private skills to check")
        for host in ssm.SYMLINK_HOSTS:
            if not (REPO_ROOT / host).parent.is_dir():
                continue
            for name in names:
                link = REPO_ROOT / host / name
                self.assertTrue(link.is_symlink(),
                                f"{host}/{name} missing — run bootstrap_overlay.py")
                self.assertEqual(os.readlink(link),
                                 f"{ssm.PRIVATE_SKILL_TARGET_PREFIX}{name}")
                self.assertTrue(link.resolve().is_dir())
                self.assertNotIn(f"skills/{name}", ssm.public_skills(REPO_ROOT))

    def test_exporter_public_list_matches_frontmatter(self):
        self.assertEqual(export_public.public_skills(), ssm.public_skills(REPO_ROOT))
        for skill in ssm.public_skills(REPO_ROOT):
            self.assertIn(f"skills/{skill}", export_public.allowlist_dirs())
        for skill in ssm.private_skills(REPO_ROOT):
            self.assertNotIn(f"skills/{skill}", export_public.allowlist_dirs())

    def test_guard_uses_the_single_parser(self):
        """check_public delegates, so the guard cannot disagree with the exporter."""
        for skill_md in sorted((REPO_ROOT / "skills").glob("*/SKILL.md")):
            self.assertEqual(check_public.parse_frontmatter_visibility(skill_md),
                             ssm.frontmatter_visibility(skill_md))


if __name__ == "__main__":
    unittest.main()
