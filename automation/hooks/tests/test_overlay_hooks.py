"""Tests for the PRIVATE-OVERLAY git hooks (automation/hooks/overlay-*).

Run with (from the repo root):
    .venv/bin/python -m unittest discover \
        -s automation/hooks/tests -t automation/hooks/tests

The hooks are tracked here and symlinked into the overlay's ``.git/hooks/`` by
``automation/bootstrap_overlay.py``. Every test builds a throwaway git repo that
stands in for the overlay — the real ``private/`` repo is never staged, committed
or otherwise written to. ``gh`` is stubbed on PATH so the remote-visibility
branches run offline and deterministically.
"""
from __future__ import annotations

import contextlib
import io
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[3]
PRE_COMMIT = REPO_ROOT / "automation/hooks/overlay-pre-commit"
PRE_PUSH = REPO_ROOT / "automation/hooks/overlay-pre-push"

PRIVATE_URL = "git@github.com:owner/overlay-private.git"
OTHER_URL = "git@github.com:someone/else.git"


class HookTestCase(unittest.TestCase):
    """A throwaway git repo standing in for the overlay."""

    def setUp(self) -> None:
        self.repo = Path(tempfile.mkdtemp(prefix="overlay-hook-")).resolve()
        self.addCleanup(shutil.rmtree, self.repo, ignore_errors=True)
        self.bin = self.repo / ".stub-bin"
        self.bin.mkdir()
        # The hook resolves an interpreter as <toolkit>/.venv/bin/python, else the
        # first python3/python on PATH meeting the 3.11 floor. A checkout without
        # a .venv therefore depends on whatever PATH happens to offer — CI's
        # setup-python gives 3.12, but a bare worktree on a machine whose system
        # python3 is older resolves nothing and every test below fails on the
        # interpreter instead of on what it means to assert. Pin PATH's python3 to
        # the interpreter running these tests: the hook's own resolution logic is
        # still what runs, it just gets a deterministic answer.
        #
        # An exec WRAPPER, not a symlink: a venv interpreter reached through a
        # symlink outside the venv computes sys.prefix from the resolved path and
        # loses its own site-packages (observed: `import yaml` fails). exec'ing it
        # by its real path keeps the venv intact.
        shim = self.bin / "python3"
        shim.write_text(f'#!/bin/sh\nexec "{sys.executable}" "$@"\n', encoding="utf-8")
        shim.chmod(0o755)
        self.env = dict(os.environ)
        self.env.update({
            "PATH": f"{self.bin}{os.pathsep}{os.environ.get('PATH', '')}",
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_CONFIG_SYSTEM": "/dev/null",
            "HOME": str(self.repo),
        })
        self.env.pop("JOBHUNT_OVERLAY_MAX_FILES", None)
        self.env.pop("JOBHUNT_OVERLAY_MAX_BYTES", None)
        self.env.pop("JOBHUNT_OVERLAY_RECONCILE", None)
        self.git("init", "-q", ".")
        self.git("config", "user.email", "t@example.com")
        self.git("config", "user.name", "Test")

    # ── helpers ──────────────────────────────────────────────────────────────
    def git(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(("git", *args), cwd=self.repo, env=self.env,
                              capture_output=True, text=True, check=True)

    def write(self, rel: str, text: str = "x\n") -> Path:
        p = self.repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        return p

    def install(self, source: Path, name: str) -> Path:
        """Symlink a hook in exactly as bootstrap_overlay.py would."""
        link = self.repo / ".git/hooks" / name
        link.parent.mkdir(parents=True, exist_ok=True)
        link.symlink_to(source)
        return link

    def stub_gh(self, is_private: str) -> None:
        """A fake ``gh`` so the visibility branches run offline."""
        gh = self.bin / "gh"
        gh.write_text(f"#!/bin/sh\necho {is_private}\n", encoding="utf-8")
        gh.chmod(0o755)

    def run_hook(self, link: Path, *args: str, **env) -> subprocess.CompletedProcess:
        e = dict(self.env)
        e.update({k: str(v) for k, v in env.items()})
        return subprocess.run([str(link), *args], cwd=self.repo, env=e,
                              capture_output=True, text=True)


class TestOverlayPreCommit(HookTestCase):

    def setUp(self) -> None:
        super().setUp()
        self.write(".gitignore", "data/*/raw/\ndata/*/derived/\ndata/email/state/\n")
        self.write("README.md", "seed\n")
        self.write("data/jobs/state/cursors.yaml", "cursor: 1\n")
        self.git("add", "-A")
        self.git("commit", "-qm", "seed")
        self.hook = self.install(PRE_COMMIT, "pre-commit")
        self.env["JOBHUNT_DATA_ROOT"] = str(self.repo / "data")

    def test_ordinary_staged_set_passes(self) -> None:
        self.write("applications/notes.md")
        self.git("add", "applications/notes.md")
        r = self.run_hook(self.hook)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("OK", r.stdout)

    def test_raw_and_derived_payloads_are_refused(self) -> None:
        self.write("data/jobs/raw/page-0001.json", "{}\n")
        self.write("data/jobs/derived/postings.jsonl", "{}\n")
        self.git("add", "-f", "data/jobs/raw/page-0001.json",
                 "data/jobs/derived/postings.jsonl")
        r = self.run_hook(self.hook)
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("STORE payload path(s)", r.stderr)
        self.assertIn("data/jobs/raw/page-0001.json", r.stderr)
        self.assertIn("data/jobs/derived/postings.jsonl", r.stderr)

    def test_ignored_state_zone_force_added_is_refused(self) -> None:
        """data/email/state is .gitignore'd: only `git add -f` puts it in the index."""
        self.write("data/email/state/delta.json", "{}\n")
        self.git("add", "-f", "data/email/state/delta.json")
        r = self.run_hook(self.hook)
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("data/email/state/delta.json", r.stderr)

    def test_permitted_state_zone_passes(self) -> None:
        """data/jobs/state is tracked by owner decision — never blocked."""
        self.write("data/jobs/state/build-ledger.jsonl", "{}\n")
        self.git("add", "data/jobs/state/build-ledger.jsonl")
        self.assertEqual(self.run_hook(self.hook).returncode, 0)

    def test_already_tracked_payload_update_passes(self) -> None:
        """The guard can never block a repeat of a commit already in history."""
        self.write("data/jobs/state/cursors.yaml", "cursor: 2\n")
        self.git("add", "data/jobs/state/cursors.yaml")
        self.assertEqual(self.run_hook(self.hook).returncode, 0)

    def test_file_count_threshold(self) -> None:
        for i in range(4):
            self.write(f"applications/bulk/f{i}.md")
        self.git("add", "applications/bulk")
        ok = self.run_hook(self.hook, JOBHUNT_OVERLAY_MAX_FILES=4)
        self.assertEqual(ok.returncode, 0, ok.stdout + ok.stderr)
        bad = self.run_hook(self.hook, JOBHUNT_OVERLAY_MAX_FILES=3)
        self.assertEqual(bad.returncode, 1)
        self.assertIn("larger than any legitimate commit", bad.stderr)

    def test_byte_threshold(self) -> None:
        self.write("applications/blob.bin", "0" * 5000)
        self.git("add", "applications/blob.bin")
        ok = self.run_hook(self.hook, JOBHUNT_OVERLAY_MAX_BYTES=5000)
        self.assertEqual(ok.returncode, 0, ok.stdout + ok.stderr)
        bad = self.run_hook(self.hook, JOBHUNT_OVERLAY_MAX_BYTES=4999)
        self.assertEqual(bad.returncode, 1)
        self.assertIn("larger than any legitimate commit", bad.stderr)

    def test_default_thresholds_clear_the_repos_biggest_real_commit(self) -> None:
        """The documented limits sit above the measured historical maximum."""
        text = PRE_COMMIT.read_text(encoding="utf-8")
        self.assertIn("JOBHUNT_OVERLAY_MAX_FILES:-500", text)
        self.assertIn("JOBHUNT_OVERLAY_MAX_BYTES:-134217728", text)
        self.assertGreater(500, 291)                 # max files ever committed
        self.assertGreater(134217728, 76877876)      # max bytes ever committed

    def test_unreachable_toolkit_fails_closed(self) -> None:
        """A copied (not symlinked) hook cannot find the toolkit — it must refuse."""
        copied = self.repo / ".git/hooks/pre-commit-copy"
        shutil.copy2(PRE_COMMIT, copied)
        self.write("applications/notes.md")
        self.git("add", "applications/notes.md")
        r = self.run_hook(copied)
        self.assertEqual(r.returncode, 1)
        self.assertIn("cannot locate the toolkit", r.stderr)

    def test_reports_the_reconciler_skip_rather_than_staying_silent(self) -> None:
        self.write("applications/notes.md")
        self.git("add", "applications/notes.md")
        r = self.run_hook(self.hook)
        self.assertIn("no private-scope reconciler applies", r.stdout)

    def test_the_toolkit_reconciler_is_opt_in_not_auto_enabled(self) -> None:
        """A ``--root`` flag on the toolkit reconciler must not arm this hook alone.

        It shipped (2026-08-07) as a PUBLIC-tree benchmark affordance. Auto-arming
        on its mere existence would point PUBLIC checks at an overlay, where
        ``skill-manifests`` fires on the overlay's own ``skills/`` and then imports
        ``sync_skill_manifests`` from a path no overlay has — a traceback on every
        private commit. The default stays the reported skip; the opt-in is loud.
        """
        self.write("applications/notes.md")
        self.git("add", "applications/notes.md")
        default = self.run_hook(self.hook)
        self.assertEqual(default.returncode, 0, default.stdout + default.stderr)
        self.assertIn("no private-scope reconciler applies", default.stdout)
        self.assertNotIn("scoped to this overlay", default.stdout)

        # An overlay the toolkit reconciler can meaningfully check has at least
        # one process root; --root refuses a tree carrying none rather than
        # reporting "OK (9 checks clean)" for a tree it never inspected.
        (self.repo / "tasks").mkdir(exist_ok=True)
        opted_in = self.run_hook(self.hook, JOBHUNT_OVERLAY_RECONCILE="1")
        self.assertIn("scoped to this overlay", opted_in.stdout)
        self.assertEqual(opted_in.returncode, 0, opted_in.stdout + opted_in.stderr)

    def test_the_opt_in_refuses_an_overlay_with_no_process_roots(self) -> None:
        """Pointing the reconciler at a tree with nothing to check must not read green.

        Every check no-ops when its root is absent, so before the guard an
        overlay carrying no process folders came back "OK (9 checks clean)".
        """
        self.write("applications/notes.md")
        self.git("add", "applications/notes.md")
        r = self.run_hook(self.hook, JOBHUNT_OVERLAY_RECONCILE="1")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("never inspected", r.stdout + r.stderr)

    def test_only_the_literal_one_arms_the_toolkit_reconciler(self) -> None:
        """Turning it OFF must not turn it on.

        The test was ``-n`` (non-empty), so exporting
        JOBHUNT_OVERLAY_RECONCILE=0 to disable the branch ARMED it — and armed,
        it points the PUBLIC reconciler at the overlay, which raises
        ModuleNotFoundError and blocks every private commit.
        """
        for value in ("0", "false", "off", "no", ""):
            with self.subTest(value=value):
                r = self.run_hook(self.hook, JOBHUNT_OVERLAY_RECONCILE=value)
                self.assertNotIn("scoped to this overlay", r.stdout,
                                 f"{value!r} must not arm the branch")
                self.assertIn("no private-scope reconciler applies", r.stdout)


class TestOverlayPrePush(HookTestCase):

    def setUp(self) -> None:
        super().setUp()
        self.hook = self.install(PRE_PUSH, "pre-push")
        self.stub_gh("true")

    def test_no_configured_remote_fails_closed(self) -> None:
        r = self.run_hook(self.hook, "origin", PRIVATE_URL)
        self.assertEqual(r.returncode, 1)
        self.assertIn("cannot determine this repo's private remote", r.stderr)

    def test_matching_origin_passes(self) -> None:
        self.git("remote", "add", "origin", PRIVATE_URL)
        r = self.run_hook(self.hook, "origin", PRIVATE_URL)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("is PRIVATE (verified via gh)", r.stdout)

    def test_url_shapes_normalise(self) -> None:
        self.git("remote", "add", "origin", PRIVATE_URL)
        r = self.run_hook(self.hook, "origin",
                          "https://github.com/Owner/overlay-private")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_other_destination_is_refused(self) -> None:
        self.git("remote", "add", "origin", PRIVATE_URL)
        r = self.run_hook(self.hook, "upstream", OTHER_URL)
        self.assertEqual(r.returncode, 1)
        self.assertIn("NOT this overlay's private remote", r.stderr)

    def test_public_destination_is_refused_even_when_it_is_origin(self) -> None:
        self.git("remote", "add", "origin", PRIVATE_URL)
        self.stub_gh("false")
        r = self.run_hook(self.hook, "origin", PRIVATE_URL)
        self.assertEqual(r.returncode, 1)
        self.assertIn("is a PUBLIC repository", r.stderr)

    def test_explicit_pin_wins_over_origin(self) -> None:
        self.git("remote", "add", "origin", OTHER_URL)
        self.git("config", "jobhunt.privateRemote", PRIVATE_URL)
        refused = self.run_hook(self.hook, "origin", OTHER_URL)
        self.assertEqual(refused.returncode, 1)
        self.assertIn("jobhunt.privateRemote", refused.stderr)
        allowed = self.run_hook(self.hook, "origin", PRIVATE_URL)
        self.assertEqual(allowed.returncode, 0, allowed.stdout + allowed.stderr)

    def test_empty_destination_url_is_refused(self) -> None:
        self.git("remote", "add", "origin", PRIVATE_URL)
        r = self.run_hook(self.hook, "origin", "")
        self.assertEqual(r.returncode, 1)
        self.assertIn("no destination URL", r.stderr)

    def test_non_github_destination_warns_but_allows_on_url_match(self) -> None:
        url = "git@git.example.com:owner/overlay.git"
        self.git("remote", "add", "origin", url)
        r = self.run_hook(self.hook, "origin", url)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("visibility cannot be verified", r.stdout)


def _bootstrap():
    sys.path.insert(0, str(REPO_ROOT / "automation"))
    import bootstrap_overlay  # noqa: E402
    return bootstrap_overlay


class TestBootstrapWiring(unittest.TestCase):
    """bootstrap_overlay.py is what puts these hooks in private/.git/hooks/."""

    def test_overlay_hooks_are_declared_and_executable(self) -> None:
        bootstrap_overlay = _bootstrap()
        self.assertEqual(bootstrap_overlay.OVERLAY_HOOKS,
                         {"pre-commit": "overlay-pre-commit",
                          "pre-push": "overlay-pre-push"})
        for name in bootstrap_overlay.OVERLAY_HOOKS.values():
            path = REPO_ROOT / "automation/hooks" / name
            self.assertTrue(path.is_file(), f"{name} missing")
            self.assertTrue(os.access(path, os.X_OK), f"{name} is not executable")

    def test_shared_dispatcher_runs_each_invoking_worktrees_hook_body(self) -> None:
        """Shared metadata must not make a linked branch run primary's hook."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "primary"
            linked = Path(td) / "linked"
            root.mkdir()
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.email", "t@example.com"],
                           cwd=root, check=True)
            subprocess.run(["git", "config", "user.name", "Test"],
                           cwd=root, check=True)
            source = root / "automation/hooks/test-pre-commit"
            source.parent.mkdir(parents=True)
            source.write_text(
                '#!/bin/sh\nprintf "primary\\n" > "$HOOK_MARKER"\n',
                encoding="utf-8")
            source.chmod(0o755)
            (root / "seed").write_text("seed\n", encoding="utf-8")
            subprocess.run(["git", "add", "seed", "automation"], cwd=root, check=True)
            subprocess.run(["git", "commit", "-qm", "seed"], cwd=root, check=True)
            subprocess.run(["git", "worktree", "add", "-q", "-b", "linked-test",
                            str(linked)], cwd=root, check=True)
            linked_source = linked / "automation/hooks/test-pre-commit"
            linked_source.write_text(
                '#!/bin/sh\nprintf "linked\\n" > "$HOOK_MARKER"\n',
                encoding="utf-8")
            linked_source.chmod(0o755)
            subprocess.run(["git", "add", "automation/hooks/test-pre-commit"],
                           cwd=linked, check=True)
            subprocess.run(["git", "commit", "-qm", "linked hook body"],
                           cwd=linked, check=True)

            bootstrap_overlay = _bootstrap()
            old_root = bootstrap_overlay.REPO_ROOT
            self.addCleanup(setattr, bootstrap_overlay, "REPO_ROOT", old_root)
            bootstrap_overlay.REPO_ROOT = linked
            hooks_dir = bootstrap_overlay._git_hooks_dir(linked)
            self.assertEqual(hooks_dir, (root / ".git/hooks").resolve())
            self.assertNotEqual(
                hooks_dir, (root / ".git/worktrees/linked/hooks").resolve())

            # Exercise migration from the old shared symlink design.
            legacy = hooks_dir / "pre-commit"
            if legacy.exists() or legacy.is_symlink():
                legacy.unlink()
            legacy.symlink_to(source)
            results: list[tuple[str, str]] = []
            bootstrap_overlay._install_toolkit_hooks(
                hooks_dir, {"pre-commit": "test-pre-commit"}, check=False,
                results=results)
            dispatcher = hooks_dir / "pre-commit"
            self.assertTrue(dispatcher.is_file())
            self.assertFalse(dispatcher.is_symlink())
            self.assertIn(bootstrap_overlay.TOOLKIT_HOOK_MARKER,
                          dispatcher.read_text(encoding="utf-8"))
            self.assertTrue(any(status == bootstrap_overlay.UPDATE
                                for status, _ in results))

            marker = Path(td) / "hook-ran"
            env = dict(os.environ, HOOK_MARKER=str(marker))
            (linked / "from-linked").write_text("changed\n", encoding="utf-8")
            subprocess.run(["git", "add", "from-linked"], cwd=linked, check=True)
            committed = subprocess.run(
                ["git", "commit", "-qm", "exercise linked hook"], cwd=linked,
                env=env, capture_output=True, text=True)
            self.assertEqual(committed.returncode, 0,
                             committed.stdout + committed.stderr)
            self.assertEqual(marker.read_text(encoding="utf-8"), "linked\n")

            marker.unlink()
            (root / "from-primary").write_text("changed\n", encoding="utf-8")
            subprocess.run(["git", "add", "from-primary"], cwd=root, check=True)
            committed = subprocess.run(
                ["git", "commit", "-qm", "exercise primary hook"], cwd=root,
                env=env, capture_output=True, text=True)
            self.assertEqual(committed.returncode, 0,
                             committed.stdout + committed.stderr)
            self.assertEqual(marker.read_text(encoding="utf-8"), "primary\n")

    def test_overlay_hook_is_durable_copy_and_foreign_hook_is_preserved(self) -> None:
        """Overlay hook metadata never points into a disposable public worktree."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "toolkit"
            hooks_dir = Path(td) / "overlay.git/hooks"
            source = root / "automation/hooks/test-overlay-hook"
            source.parent.mkdir(parents=True)
            source.write_text(
                '#!/bin/sh\nprintf "overlay-copy\\n" > "$HOOK_MARKER"\n',
                encoding="utf-8")
            source.chmod(0o755)
            hooks_dir.mkdir(parents=True)

            bootstrap_overlay = _bootstrap()
            old_root = bootstrap_overlay.REPO_ROOT
            self.addCleanup(setattr, bootstrap_overlay, "REPO_ROOT", old_root)
            bootstrap_overlay.REPO_ROOT = root
            results: list[tuple[str, str]] = []
            bootstrap_overlay._install_overlay_hooks(
                hooks_dir, {"pre-commit": "test-overlay-hook"}, check=False,
                results=results)
            installed = hooks_dir / "pre-commit"
            self.assertTrue(installed.is_file())
            self.assertFalse(installed.is_symlink())
            self.assertIn(bootstrap_overlay.OVERLAY_HOOK_MARKER,
                          installed.read_text(encoding="utf-8"))

            source.unlink()
            marker = Path(td) / "overlay-ran"
            ran = subprocess.run([str(installed)],
                                 env=dict(os.environ, HOOK_MARKER=str(marker)),
                                 capture_output=True, text=True)
            self.assertEqual(ran.returncode, 0, ran.stdout + ran.stderr)
            self.assertEqual(marker.read_text(encoding="utf-8"), "overlay-copy\n")

            foreign = hooks_dir / "pre-push"
            foreign.write_text("#!/bin/sh\necho foreign\n", encoding="utf-8")
            source.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            source.chmod(0o755)
            results = []
            bootstrap_overlay._install_overlay_hooks(
                hooks_dir, {"pre-push": "test-overlay-hook"}, check=False,
                results=results)
            self.assertEqual(foreign.read_text(encoding="utf-8"),
                             "#!/bin/sh\necho foreign\n")
            self.assertTrue(any(status == bootstrap_overlay.WARN
                                for status, _ in results))

    def test_relative_core_hooks_path_is_resolved_from_linked_worktree(self) -> None:
        """``rev-parse --git-path`` also follows Git's hooksPath semantics."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "primary"
            linked = Path(td) / "linked"
            root.mkdir()
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.email", "t@example.com"],
                           cwd=root, check=True)
            subprocess.run(["git", "config", "user.name", "Test"],
                           cwd=root, check=True)
            (root / "seed").write_text("seed\n", encoding="utf-8")
            subprocess.run(["git", "add", "seed"], cwd=root, check=True)
            subprocess.run(["git", "commit", "-qm", "seed"], cwd=root, check=True)
            subprocess.run(["git", "worktree", "add", "-q", "--detach", str(linked)],
                           cwd=root, check=True)
            subprocess.run(["git", "config", "core.hooksPath", "runtime-hooks"],
                           cwd=root, check=True)

            bootstrap_overlay = _bootstrap()
            self.assertEqual(bootstrap_overlay._git_hooks_dir(linked),
                             (linked / "runtime-hooks").resolve())


class TestBootstrapWritesNothingIntoThePublicTree(unittest.TestCase):
    """The phase-4 invariant, asserted on the PLAN rather than on a live run.

    ``bootstrap_overlay`` used to create inbound symlinks inside the public
    ``skills/`` tree, including paths whose names were private. Nothing it plans
    may land there any more; an overlay-only skill reaches the runtime through
    repository-locally ignored agent host trees instead.
    """

    def _tree(self, td: str):
        """A synthetic repo root with an overlay holding two private skills."""
        root = Path(td)
        bootstrap_overlay = _bootstrap()
        self.addCleanup(setattr, bootstrap_overlay, "REPO_ROOT",
                        bootstrap_overlay.REPO_ROOT)
        bootstrap_overlay.REPO_ROOT = root
        for host in bootstrap_overlay.SKILL_HOSTS:
            (root / host).parent.mkdir(parents=True, exist_ok=True)
        (root / "skills/job-search/profiles").mkdir(parents=True)
        for name in ("hidden-a", "hidden-b"):
            d = root / "private/skills" / name
            d.mkdir(parents=True)
            (d / "SKILL.md").write_text("---\nvisibility: private\n---\n",
                                        encoding="utf-8")
        # Neighbours that must NOT be linked: the private notes folder and a
        # personal search profile.
        (root / "private/skills/references_private/job-search").mkdir(parents=True)
        (root / "private/job-search-profiles").mkdir(parents=True)
        (root / "private/job-search-profiles/personal.yaml").write_text(
            "titles: {}\n", encoding="utf-8")
        return root, bootstrap_overlay

    def test_no_planned_link_lands_under_skills(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root, bootstrap_overlay = self._tree(td)
            planned = bootstrap_overlay._private_skill_links(root / "private")
            rels = sorted(link.relative_to(root).as_posix() for link, _ in planned)
            self.assertEqual(rels, [
                ".agents/skills/hidden-a", ".agents/skills/hidden-b",
                ".claude/skills/hidden-a", ".claude/skills/hidden-b",
                ".cursor/skills/hidden-a", ".cursor/skills/hidden-b",
            ])
            for rel in rels:
                self.assertFalse(rel.startswith("skills/"), rel)

    def test_links_point_straight_at_the_overlay(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root, bootstrap_overlay = self._tree(td)
            for link, dest in bootstrap_overlay._private_skill_links(root / "private"):
                self.assertEqual(dest.parent, root / "private/skills")
                self.assertEqual(bootstrap_overlay._rel_target(link, dest),
                                 f"../../private/skills/{dest.name}")

    def test_notes_folder_and_profiles_are_never_linked(self) -> None:
        """Only a dir holding a SKILL.md is a skill — accessors reach the rest."""
        with tempfile.TemporaryDirectory() as td:
            root, bootstrap_overlay = self._tree(td)
            names = {dest.name
                     for _, dest in bootstrap_overlay._private_skill_links(root / "private")}
            self.assertNotIn("references_private", names)
            self.assertEqual(names, {"hidden-a", "hidden-b"})
            self.assertEqual(
                sorted(p.name for p in (root / "skills/job-search/profiles").iterdir()),
                [])

    def test_an_absent_agent_root_is_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root, bootstrap_overlay = self._tree(td)
            shutil.rmtree(root / ".cursor")
            hosts = {link.relative_to(root).parts[0]
                     for link, _ in bootstrap_overlay._private_skill_links(root / "private")}
            self.assertEqual(hosts, {".agents", ".claude"})

    def test_local_excludes_hide_all_three_runtime_adapters(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root, bootstrap_overlay = self._tree(td)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            exclude = root / ".git/info/exclude"
            exclude.write_text("# user-owned line\n*.scratch\n", encoding="utf-8")
            planned = bootstrap_overlay._private_skill_links(root / "private")
            results: list[tuple[str, str]] = []

            self.assertTrue(bootstrap_overlay._sync_local_excludes(
                [link for link, _ in planned], check=False, results=results))

            text = exclude.read_text(encoding="utf-8")
            self.assertIn("# user-owned line\n*.scratch\n", text)
            self.assertEqual(text.count(bootstrap_overlay.LOCAL_EXCLUDE_BEGIN), 1)
            self.assertEqual(text.count(bootstrap_overlay.LOCAL_EXCLUDE_END), 1)
            for link, _ in planned:
                rel = link.relative_to(root).as_posix()
                self.assertIn(f"/{rel}\n", text)
                probe = subprocess.run(
                    ["git", "-C", str(root), "check-ignore", "--no-index", rel],
                    capture_output=True, text=True)
                self.assertEqual(probe.returncode, 0, probe.stderr)

    def test_local_exclude_sync_is_idempotent_and_removes_stale_owned_rows(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root, bootstrap_overlay = self._tree(td)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            planned = bootstrap_overlay._private_skill_links(root / "private")
            results: list[tuple[str, str]] = []
            links = [link for link, _ in planned]
            self.assertTrue(bootstrap_overlay._sync_local_excludes(
                links, check=False, results=results))
            exclude = root / ".git/info/exclude"
            before = exclude.read_text(encoding="utf-8")

            results = []
            self.assertTrue(bootstrap_overlay._sync_local_excludes(
                links, check=True, results=results))
            self.assertEqual(exclude.read_text(encoding="utf-8"), before)
            self.assertEqual(results, [
                (bootstrap_overlay.OK,
                 "repository-local overlay skill excludes already correct")
            ])

            kept = [link for link in links if link.name == "hidden-a"]
            results = []
            self.assertTrue(bootstrap_overlay._sync_local_excludes(
                kept, check=False, results=results))
            after = exclude.read_text(encoding="utf-8")
            self.assertNotIn("hidden-b", after)
            self.assertIn("hidden-a", after)

    def test_shared_excludes_union_adapters_from_all_live_worktrees(self) -> None:
        """One worktree cannot expose another worktree's private adapter."""
        with tempfile.TemporaryDirectory() as td:
            primary = Path(td) / "primary"
            worktree_a = Path(td) / "worktree-a"
            worktree_b = Path(td) / "worktree-b"
            primary.mkdir()
            subprocess.run(["git", "init", "-q"], cwd=primary, check=True)
            subprocess.run(["git", "config", "user.email", "t@example.com"],
                           cwd=primary, check=True)
            subprocess.run(["git", "config", "user.name", "Test"],
                           cwd=primary, check=True)
            (primary / "seed").write_text("seed\n", encoding="utf-8")
            subprocess.run(["git", "add", "seed"], cwd=primary, check=True)
            subprocess.run(["git", "commit", "-qm", "seed"], cwd=primary, check=True)
            subprocess.run(["git", "worktree", "add", "-q", "-b", "adapter-a",
                            str(worktree_a)], cwd=primary, check=True)
            subprocess.run(["git", "worktree", "add", "-q", "-b", "adapter-b",
                            str(worktree_b)], cwd=primary, check=True)

            links: dict[str, Path] = {}
            for worktree, name in ((worktree_a, "hidden-a"),
                                   (worktree_b, "hidden-b")):
                dest = worktree / "private/skills" / name
                dest.mkdir(parents=True)
                (dest / "SKILL.md").write_text("---\nvisibility: private\n---\n",
                                                encoding="utf-8")
                link = worktree / ".agents/skills" / name
                link.parent.mkdir(parents=True)
                link.symlink_to(f"../../private/skills/{name}")
                links[name] = link

            bootstrap_overlay = _bootstrap()
            old_root = bootstrap_overlay.REPO_ROOT
            self.addCleanup(setattr, bootstrap_overlay, "REPO_ROOT", old_root)
            bootstrap_overlay.REPO_ROOT = worktree_a
            results: list[tuple[str, str]] = []
            self.assertTrue(bootstrap_overlay._sync_local_excludes(
                [links["hidden-a"]], check=False, results=results))

            exclude = primary / ".git/info/exclude"
            text = exclude.read_text(encoding="utf-8")
            self.assertIn("/.agents/skills/hidden-a\n", text)
            self.assertIn("/.agents/skills/hidden-b\n", text)
            for worktree, name in ((worktree_a, "hidden-a"),
                                   (worktree_b, "hidden-b")):
                ignored = subprocess.run(
                    ["git", "check-ignore", "--no-index", f".agents/skills/{name}"],
                    cwd=worktree, capture_output=True, text=True)
                self.assertEqual(ignored.returncode, 0, ignored.stderr)

            links["hidden-b"].unlink()
            results = []
            self.assertTrue(bootstrap_overlay._sync_local_excludes(
                [links["hidden-a"]], check=False, results=results))
            text = exclude.read_text(encoding="utf-8")
            self.assertIn("/.agents/skills/hidden-a\n", text)
            self.assertNotIn("hidden-b", text)

    def test_incomplete_worktree_inventory_retains_managed_excludes(self) -> None:
        """Inventory failure is fail-safe: stale ignores beat a private-path leak."""
        with tempfile.TemporaryDirectory() as td:
            root, bootstrap_overlay = self._tree(td)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            exclude = root / ".git/info/exclude"
            exclude.write_text(
                f"{bootstrap_overlay.LOCAL_EXCLUDE_BEGIN}\n"
                "/.agents/skills/from-another-worktree\n"
                f"{bootstrap_overlay.LOCAL_EXCLUDE_END}\n",
                encoding="utf-8")
            original = bootstrap_overlay._git_worktree_paths
            self.addCleanup(setattr, bootstrap_overlay, "_git_worktree_paths", original)
            bootstrap_overlay._git_worktree_paths = lambda repo=None: None

            planned = bootstrap_overlay._private_skill_links(root / "private")
            results: list[tuple[str, str]] = []
            self.assertTrue(bootstrap_overlay._sync_local_excludes(
                [link for link, _ in planned], check=False, results=results))
            self.assertIn("/.agents/skills/from-another-worktree\n",
                          exclude.read_text(encoding="utf-8"))

    def test_malformed_successful_porcelain_retains_managed_excludes(self) -> None:
        """A zero exit with an incomplete record is still an unsafe inventory."""
        with tempfile.TemporaryDirectory() as td:
            root, bootstrap_overlay = self._tree(td)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            exclude = root / ".git/info/exclude"
            exclude.write_text(
                f"{bootstrap_overlay.LOCAL_EXCLUDE_BEGIN}\n"
                "/.agents/skills/from-omitted-worktree\n"
                f"{bootstrap_overlay.LOCAL_EXCLUDE_END}\n",
                encoding="utf-8")
            real_run = subprocess.run

            def malformed_worktree_list(args, *positional, **keywords):
                if list(args)[-3:] == ["worktree", "list", "--porcelain"]:
                    return subprocess.CompletedProcess(
                        args, 0,
                        stdout=(f"worktree {root}\n"
                                "HEAD 0123456789abcdef0123456789abcdef01234567\n\n"),
                        stderr="")
                return real_run(args, *positional, **keywords)

            planned = bootstrap_overlay._private_skill_links(root / "private")
            results: list[tuple[str, str]] = []
            with mock.patch.object(bootstrap_overlay.subprocess, "run",
                                   side_effect=malformed_worktree_list):
                self.assertIsNone(bootstrap_overlay._git_worktree_paths())
                self.assertTrue(bootstrap_overlay._sync_local_excludes(
                    [link for link, _ in planned], check=False, results=results))
            self.assertIn("/.agents/skills/from-omitted-worktree\n",
                          exclude.read_text(encoding="utf-8"))

    def test_worktree_parser_handles_documented_record_variants(self) -> None:
        bootstrap_overlay = _bootstrap()
        live = Path("/tmp/documented-live-worktree")
        output = (
            "worktree /tmp/documented-bare-repo\n"
            "bare\n\n"
            f"worktree {live}\n"
            "HEAD 0123456789abcdef0123456789abcdef01234567\n"
            "detached\n"
            "locked owner requested\n\n"
            "worktree /tmp/documented-prunable-worktree\n"
            "HEAD fedcba9876543210fedcba9876543210fedcba98\n"
            "branch refs/heads/old\n"
            "prunable gitdir file points to non-existent location\n\n"
        )
        completed = subprocess.CompletedProcess([], 0, stdout=output, stderr="")
        with mock.patch.object(bootstrap_overlay.subprocess, "run",
                               return_value=completed):
            self.assertEqual(bootstrap_overlay._git_worktree_paths(),
                             [live.resolve()])

    def test_bootstrap_removes_only_obsolete_generated_adapters(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root, bootstrap_overlay = self._tree(td)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            foreign = root / ".cursor/skills/third-party"
            foreign.mkdir(parents=True)

            self.assertEqual(bootstrap_overlay.bootstrap(check=False), 0)
            obsolete = [root / host / "hidden-b"
                        for host in bootstrap_overlay.SKILL_HOSTS]
            self.assertTrue(all(link.is_symlink() for link in obsolete))

            shutil.rmtree(root / "private/skills/hidden-b")
            self.assertEqual(bootstrap_overlay.bootstrap(check=False), 0)

            self.assertTrue(all(not link.is_symlink() and not link.exists()
                                for link in obsolete))
            self.assertTrue(foreign.is_dir())
            exclude = (root / ".git/info/exclude").read_text(encoding="utf-8")
            self.assertNotIn("hidden-b", exclude)
            self.assertIn("hidden-a", exclude)


class TestBootstrapRepairsBrokenHookInstalls(unittest.TestCase):
    """A hook git cannot run is worse than no hook: it looks installed.

    Moving ``hooks/`` to ``automation/hooks/`` left every existing checkout with
    ``.git/hooks/pre-commit -> ../../hooks/pre-commit``, a dangling link git skips
    in silence — so commits and pushes ran with no leak guard while bootstrap
    reported the link as foreign and exited 0. Bootstrap now replaces those shapes
    with managed dispatchers or durable copies, and ``--check`` is red whenever a
    tracked hook is not installed.
    """

    def _tree(self, td: str):
        """A synthetic repo root: real git dirs, stub hook sources, no overlay."""
        root = Path(td).resolve()
        bootstrap_overlay = _bootstrap()
        self.addCleanup(setattr, bootstrap_overlay, "REPO_ROOT",
                        bootstrap_overlay.REPO_ROOT)
        bootstrap_overlay.REPO_ROOT = root
        subprocess.run(["git", "init", "-q"], cwd=root, check=True)
        (root / ".git/hooks").mkdir(parents=True, exist_ok=True)
        hooks = root / "automation/hooks"
        hooks.mkdir(parents=True)
        for name in ("pre-commit", "pre-push",
                     "overlay-pre-commit", "overlay-pre-push"):
            script = hooks / name
            script.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            script.chmod(0o755)
        return root, bootstrap_overlay

    def _run(self, bootstrap_overlay, *, check: bool) -> tuple[int, str]:
        report = io.StringIO()
        with contextlib.redirect_stdout(report):
            code = bootstrap_overlay.bootstrap(check=check)
        return code, report.getvalue()

    def _link(self, root: Path, rel: str, target: str) -> Path:
        link = root / rel
        link.parent.mkdir(parents=True, exist_ok=True)
        link.symlink_to(target)
        return link

    # ── the incident: a link left behind by the hooks/ -> automation/hooks/ move ──
    def test_dangling_retired_path_link_is_repaired_by_apply(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root, bootstrap_overlay = self._tree(td)
            link = self._link(root, ".git/hooks/pre-commit", "../../hooks/pre-commit")
            self.assertFalse(link.exists(), "fixture must start dangling")

            code, report = self._run(bootstrap_overlay, check=False)

            self.assertEqual(code, 0, report)
            self.assertTrue(link.is_file())
            self.assertFalse(link.is_symlink())
            self.assertIn(bootstrap_overlay.TOOLKIT_HOOK_MARKER,
                          link.read_text(encoding="utf-8"))
            self.assertIn("was: ../../hooks/pre-commit", report)

    def test_check_is_red_on_a_dangling_hook_and_changes_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root, bootstrap_overlay = self._tree(td)
            link = self._link(root, ".git/hooks/pre-push", "../../hooks/pre-push")

            code, report = self._run(bootstrap_overlay, check=True)

            self.assertEqual(code, 1, report)
            self.assertEqual(os.readlink(link), "../../hooks/pre-push")
            self.assertIn("NOT wired to their tracked source", report)
            self.assertIn(".git/hooks/pre-push", report)

    def test_check_is_red_when_a_hook_is_missing_and_green_after_apply(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root, bootstrap_overlay = self._tree(td)

            missing, _ = self._run(bootstrap_overlay, check=True)
            self.assertEqual(missing, 1)

            self.assertEqual(self._run(bootstrap_overlay, check=False)[0], 0)

            wired, report = self._run(bootstrap_overlay, check=True)
            self.assertEqual(wired, 0, report)
            self.assertNotIn("NOT wired", report)
            for name in ("pre-commit", "pre-push"):
                installed = root / ".git/hooks" / name
                self.assertTrue(installed.is_file())
                self.assertFalse(installed.is_symlink())
                self.assertIn(bootstrap_overlay.TOOLKIT_HOOK_MARKER,
                              installed.read_text(encoding="utf-8"))

    def test_apply_installs_workspace_alias_and_check_accepts_it(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root, bootstrap_overlay = self._tree(td)
            dashboard = root / "automation/workspace/status.py"
            dashboard.parent.mkdir(parents=True, exist_ok=True)
            dashboard.write_text("#!/bin/sh\necho dashboard-ran\n", encoding="utf-8")
            dashboard.chmod(0o755)

            code, report = self._run(bootstrap_overlay, check=False)

            self.assertEqual(code, 0, report)
            value = subprocess.run(
                ["git", "config", "--local", "--get", "alias.ws"],
                cwd=root, capture_output=True, text=True, check=True)
            self.assertEqual(value.stdout.strip(),
                             bootstrap_overlay.WORKSPACE_ALIAS_VALUE)
            invoked = subprocess.run(
                ["git", "ws"], cwd=root, capture_output=True, text=True)
            self.assertEqual(invoked.returncode, 0, invoked.stderr)
            self.assertEqual(invoked.stdout.strip(), "dashboard-ran")
            code, report = self._run(bootstrap_overlay, check=True)
            self.assertEqual(code, 0, report)
            self.assertIn("git ws alias already correct", report)

    def test_check_reports_missing_workspace_alias_without_writing_it(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root, bootstrap_overlay = self._tree(td)
            hooks_dir = root / ".git/hooks"
            bootstrap_overlay._install_toolkit_hooks(
                hooks_dir, bootstrap_overlay.TOOLKIT_HOOKS, False, [])

            code, report = self._run(bootstrap_overlay, check=True)

            self.assertEqual(code, 1, report)
            missing = subprocess.run(
                ["git", "config", "--local", "--get", "alias.ws"],
                cwd=root, capture_output=True, text=True)
            self.assertEqual(missing.returncode, 1)
            self.assertIn("git ws alias is not installed", report)

    def test_conflicting_workspace_alias_is_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root, bootstrap_overlay = self._tree(td)
            subprocess.run(
                ["git", "config", "--local", "alias.ws", "status --short"],
                cwd=root, check=True)

            code, report = self._run(bootstrap_overlay, check=False)

            self.assertEqual(code, 0, report)
            value = subprocess.run(
                ["git", "config", "--local", "--get", "alias.ws"],
                cwd=root, capture_output=True, text=True, check=True)
            self.assertEqual(value.stdout.strip(), "status --short")
            self.assertIn("user-owned", report)
            self.assertEqual(self._run(bootstrap_overlay, check=True)[0], 1)

    def test_a_link_mis_wired_inside_the_tracked_dir_is_repaired(self) -> None:
        """Ours, pointing at the wrong tracked hook — repair, do not warn."""
        with tempfile.TemporaryDirectory() as td:
            root, bootstrap_overlay = self._tree(td)
            link = self._link(root, ".git/hooks/pre-commit",
                              "../../automation/hooks/pre-push")

            code, report = self._run(bootstrap_overlay, check=False)

            self.assertEqual(code, 0, report)
            self.assertTrue(link.is_file())
            self.assertFalse(link.is_symlink())
            self.assertIn(bootstrap_overlay.TOOLKIT_HOOK_MARKER,
                          link.read_text(encoding="utf-8"))

    # ── the other side of the rule: a real third-party hook is untouchable ──────
    def test_a_foreign_hook_file_survives_apply_and_still_fails_check(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root, bootstrap_overlay = self._tree(td)
            foreign = root / ".git/hooks/pre-commit"
            foreign.write_text("#!/bin/sh\necho someone elses hook\n", encoding="utf-8")
            before = foreign.read_text(encoding="utf-8")

            code, report = self._run(bootstrap_overlay, check=False)

            self.assertEqual(code, 0, report)
            self.assertFalse(foreign.is_symlink())
            self.assertEqual(foreign.read_text(encoding="utf-8"), before)
            self.assertIn("leaving it untouched", report)
            # It still means the guard does not run, so the health check says so.
            self.assertEqual(self._run(bootstrap_overlay, check=True)[0], 1)

    def test_a_foreign_symlink_that_resolves_elsewhere_is_left_alone(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root, bootstrap_overlay = self._tree(td)
            other = root / "third-party/husky-pre-commit"
            other.parent.mkdir()
            other.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            link = self._link(root, ".git/hooks/pre-commit",
                              "../../third-party/husky-pre-commit")

            code, report = self._run(bootstrap_overlay, check=False)

            self.assertEqual(code, 0, report)
            self.assertEqual(link.resolve(), other)
            self.assertIn("is a foreign symlink", report)

    # ── the overlay's own hooks follow the same rule ────────────────────────────
    def test_a_dangling_overlay_hook_is_repaired_too(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root, bootstrap_overlay = self._tree(td)
            private = root / "private"
            subprocess.run(["git", "init", "-q", str(private)], check=True)
            (private / ".git/hooks").mkdir(parents=True, exist_ok=True)
            link = self._link(root, "private/.git/hooks/pre-commit",
                              "../../../hooks/overlay-pre-commit")

            code, report = self._run(bootstrap_overlay, check=False)

            self.assertEqual(code, 0, report)
            self.assertTrue(link.is_file())
            self.assertFalse(link.is_symlink())
            self.assertIn(bootstrap_overlay.OVERLAY_HOOK_MARKER,
                          link.read_text(encoding="utf-8"))
            self.assertIn("[overlay]", report)


if __name__ == "__main__":
    unittest.main()
