"""Tests for the read-only post-merge cutover planner.

Run with (from the repo root):
    .venv/bin/python -m unittest discover automation/cutover/tests

The two properties that must never regress:

  * **the planner writes nothing.** ``ReadOnlyRunTests`` snapshots the repository
    — porcelain status, ``HEAD``, every ref, the object store, and ``.git/index``
    — around a full run and requires byte equality.  That is what proves
    ``git hash-object`` is called without ``-w`` and that ``git status`` never
    refreshes the index behind the caller's back;
  * **it fails closed.** Every condition in the planner's refusal table exits 3.
    A missing remote and a FAILED fetch are refusals, never "stale" — the whole
    premise of this workflow is that the prerequisites just merged, so the one
    fact that must be fresh is exactly the one that would be guessed.

The planner is exercised as a SUBPROCESS wherever an exit code is the subject,
because an exit code read any other way is not the exit code the caller sees.
Every subprocess sets ``JOBHUNT_CONFIG`` to a throwaway config, so no test can
reach the developer's real configuration or the real private overlay.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

# Make the sibling modules importable (automation/cutover/).
_CUTOVER_DIR = Path(__file__).resolve().parents[1]
if str(_CUTOVER_DIR) not in sys.path:
    sys.path.insert(0, str(_CUTOVER_DIR))

import classify_dirty as CD  # noqa: E402
import plan_cutover as P  # noqa: E402

REPO_ROOT = P.REPO_ROOT
HANDBOOK_DOC = REPO_ROOT / "docs/handbook/post-merge-cutover.md"

GIT_ENV = {
    "GIT_AUTHOR_NAME": "Cutover Test",
    "GIT_AUTHOR_EMAIL": "cutover@example.invalid",
    "GIT_COMMITTER_NAME": "Cutover Test",
    "GIT_COMMITTER_EMAIL": "cutover@example.invalid",
    "GIT_AUTHOR_DATE": "2026-01-01T00:00:00+0000",
    "GIT_COMMITTER_DATE": "2026-01-01T00:00:00+0000",
    "GIT_CONFIG_NOSYSTEM": "1",
}

CALENDAR_OLD = (
    "# Calendar\n"
    "\n"
    "- [Acme notes](../companies/acme/notes.md)\n"
    "- see `companies/acme/` for the dossier\n"
)
CALENDAR_MERGED = (
    "# Calendar\n"
    "\n"
    "- [Acme notes](companies/acme/notes.md)\n"
    "- see `me/interviews/companies/acme/` for the dossier\n"
)

PLAN_KEYS = {
    "blocking", "exit_code", "executable", "generated_at", "generator", "handoff",
    "prerequisites", "remote_knowledge", "renames", "repos", "run_id", "schema",
    "session_id", "similarity_renames", "steps", "validation_profile",
}
DIRTY_KEYS = {
    "action", "blobs", "destination_bytes_equal", "destination_exists", "ignored",
    "merged_path", "path", "rename", "residual_after_link_rebase", "residual_lines",
    "tracked", "verdict", "verdict_reason", "worktree_status",
}


class PlannerFixture(unittest.TestCase):
    """A throwaway public repo, its bare origin, and a throwaway config.yaml."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="cutover-plan-")).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.home = self.tmp / "home"
        self.home.mkdir()
        self.env = {**os.environ, **GIT_ENV, "HOME": str(self.home)}
        self.env.pop("JOBHUNT_SESSION_ID", None)
        self.env.pop("JOBHUNT_DATA_ROOT", None)

        self.origin = self.tmp / "origin.git"
        self.origin.mkdir()
        self.git("init", "-q", "--bare", ".", cwd=self.origin)
        self.git("symbolic-ref", "HEAD", "refs/heads/main", cwd=self.origin)

        self.repo = self.tmp / "repo"
        self.repo.mkdir()
        self.git("init", "-q", ".")
        self.git("symbolic-ref", "HEAD", "refs/heads/main")
        self.build_history()
        self.config_path = self.write_config()

    # -- fixture construction ----------------------------------------------
    def git(self, *args: str, cwd: Path | None = None, check: bool = True) -> str:
        completed = subprocess.run(
            ["git", *args], cwd=str(cwd or self.repo), env=self.env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)
        if check:
            self.assertEqual(
                completed.returncode, 0,
                f"git {' '.join(args)} exited {completed.returncode}: "
                f"{completed.stdout.decode('utf-8', 'replace')}")
        return completed.stdout.decode("utf-8", "replace")

    def write(self, relative: str, text: str, root: Path | None = None) -> None:
        target = (root or self.repo) / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")

    def commit(self, message: str) -> str:
        self.git("add", "-A")
        self.git("commit", "-qm", message)
        return self.git("rev-parse", "HEAD").strip()

    def build_history(self) -> None:
        """Old layout on ``main``; the merged layout published as ``origin/main``."""
        self.write(".gitignore", "scratch/\nresearch/\n")
        self.write("interviews/calendar.md", CALENDAR_OLD)
        self.write("interviews/log.md", "interview log\n")
        self.write("companies/acme/notes.md", "acme notes\n")
        self.write("conflict.md", "one\n")
        self.fork = self.commit("old layout")
        self.git("remote", "add", "origin", str(self.origin))
        self.git("push", "-q", "origin", "main")

        self.git("checkout", "-qb", "layout")
        (self.repo / "me/interviews/companies/acme").mkdir(parents=True)
        self.git("mv", "companies/acme/notes.md",
                 "me/interviews/companies/acme/notes.md")
        self.git("mv", "interviews/log.md", "me/interviews/log.md")
        self.git("mv", "interviews/calendar.md", "me/interviews/calendar.md")
        self.write("me/interviews/calendar.md", CALENDAR_MERGED)
        self.write("conflict.md", "upstream\n")
        self.merged = self.commit("person-first layout")
        self.git("push", "-q", "--force", "origin", "layout:main")

        self.git("checkout", "-q", "main")
        self.git("fetch", "-q", "origin")
        self.git("checkout", "-qb", "work")

    def write_config(self, overlay: Path | None = None) -> Path:
        path = self.tmp / "config.yaml"
        overlay_root = overlay if overlay is not None else (self.tmp / "overlay")
        path.write_text(
            "candidate:\n"
            "  name: Cutover Test\n"
            "paths:\n"
            f"  applications_root: {overlay_root}/me/applications\n"
            f"  overlay_root: {overlay_root}\n",
            encoding="utf-8")
        return path

    def make_overlay(self, root: Path | None = None) -> Path:
        overlay = root or (self.tmp / "overlay")
        overlay.mkdir(parents=True, exist_ok=True)
        self.git("init", "-q", ".", cwd=overlay)
        self.git("symbolic-ref", "HEAD", "refs/heads/main", cwd=overlay)
        self.write("me/applications/keep.md", "keep\n", root=overlay)
        self.git("add", "-A", cwd=overlay)
        self.git("commit", "-qm", "overlay base", cwd=overlay)
        origin = self.tmp / "overlay-origin.git"
        origin.mkdir()
        self.git("init", "-q", "--bare", ".", cwd=origin)
        self.git("symbolic-ref", "HEAD", "refs/heads/main", cwd=origin)
        self.git("remote", "add", "origin", str(origin), cwd=overlay)
        self.git("push", "-q", "origin", "main", cwd=overlay)
        self.git("fetch", "-q", "origin", cwd=overlay)
        return overlay

    # -- running the planner ------------------------------------------------
    def plan(self, *args: str, json_out: Path | None = None,
             env_extra: dict[str, str] | None = None):
        out = self.tmp / "plan.json" if json_out is None else json_out
        argv = [sys.executable, str(_CUTOVER_DIR / "plan_cutover.py"),
                "--public-root", str(self.repo), *args]
        if "--json-out" not in args:
            argv.extend(["--json-out", str(out)])
        env = {**self.env, "JOBHUNT_CONFIG": str(self.config_path)}
        env.update(env_extra or {})
        completed = subprocess.run(argv, cwd=str(self.tmp), env=env,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   check=False)
        payload = None
        if out.is_file():
            payload = json.loads(out.read_text())
        return completed, payload

    def codes(self, payload) -> list[str]:
        return [item["code"] for item in payload["blocking"]]


# ── the executable / needs-judgement / refused matrix ────────────────────────
class ExitCodeTests(PlannerFixture):

    def test_clean_repo_with_a_fresh_fetch_is_executable(self) -> None:
        completed, plan = self.plan("--repo", "public", "--fetch")
        self.assertEqual(completed.returncode, 0, completed.stderr.decode())
        self.assertEqual(plan["blocking"], [])
        self.assertTrue(plan["executable"])
        self.assertEqual(plan["remote_knowledge"]["state"], "fresh")
        self.assertEqual(plan["exit_code"], 0)

    def test_without_fetch_the_remote_is_stale_and_never_executable(self) -> None:
        completed, plan = self.plan("--repo", "public")
        self.assertEqual(completed.returncode, 1, completed.stderr.decode())
        self.assertEqual(plan["remote_knowledge"]["state"], "stale")
        self.assertFalse(plan["remote_knowledge"]["fetched"])
        self.assertFalse(plan["executable"])
        self.assertEqual(plan["blocking"], [])

    def test_an_agent_step_downgrades_an_otherwise_fresh_plan_to_one(self) -> None:
        self.write("interviews/calendar.md", CALENDAR_OLD + "- local todo\n")
        completed, plan = self.plan("--repo", "public", "--fetch")
        self.assertEqual(completed.returncode, 1, completed.stderr.decode())
        self.assertEqual(plan["blocking"], [])
        self.assertFalse(plan["executable"])
        kinds = {step["kind"] for step in plan["steps"]}
        self.assertIn("agent", kinds)

    def test_a_usage_error_is_argparse_two(self) -> None:
        completed, _ = self.plan("--repo", "nonsense")
        self.assertEqual(completed.returncode, 2)


# ── fail-closed: git state ───────────────────────────────────────────────────
class FailClosedGitStateTests(PlannerFixture):

    def test_an_unknown_dirty_path_refuses_and_still_reports_the_inventory(self) -> None:
        self.write("probe.json", "{}\n")
        completed, plan = self.plan("--repo", "public", "--fetch")
        self.assertEqual(completed.returncode, 3, completed.stderr.decode())
        self.assertEqual(self.codes(plan), [P.CODE_UNKNOWN_DIRTY])
        self.assertEqual(plan["blocking"][0]["subject"], "probe.json")
        self.assertTrue(plan["blocking"][0]["owner_action_required"])
        # A refusal is still a complete description of what was refused.
        inventory = plan["repos"]["public"]
        self.assertEqual(inventory["branch"], "work")
        self.assertTrue(inventory["dirty"])
        self.assertTrue(plan["renames"]["public"])

    def test_a_detached_head_refuses(self) -> None:
        self.git("checkout", "-q", "--detach", "HEAD")
        completed, plan = self.plan("--repo", "public", "--fetch")
        self.assertEqual(completed.returncode, 3)
        self.assertIn(P.CODE_DETACHED_HEAD, self.codes(plan))

    def test_an_operation_in_progress_refuses(self) -> None:
        self.write("conflict.md", "local\n")
        self.commit("local conflict edit")
        rebase = self.git("rebase", "origin/main", check=False)
        self.assertNotEqual(rebase.strip(), "", "the fixture must produce a conflict")
        completed, plan = self.plan("--repo", "public", "--fetch")
        self.assertEqual(completed.returncode, 3)
        self.assertIn(P.CODE_OPERATION_IN_PROGRESS, self.codes(plan))

    def test_a_dirty_sibling_worktree_refuses(self) -> None:
        sibling = self.tmp / "sibling"
        self.git("worktree", "add", "-q", "-b", "sibling", str(sibling), "HEAD")
        (sibling / "dirty.md").write_text("uncommitted\n")
        completed, plan = self.plan("--repo", "public", "--fetch")
        self.assertEqual(completed.returncode, 3)
        self.assertIn(P.CODE_WORKTREE_OWNED_STATE, self.codes(plan))

    def test_a_locked_sibling_worktree_refuses(self) -> None:
        sibling = self.tmp / "sibling"
        self.git("worktree", "add", "-q", "-b", "sibling", str(sibling), "HEAD")
        self.git("worktree", "lock", str(sibling))
        completed, plan = self.plan("--repo", "public", "--fetch")
        self.assertEqual(completed.returncode, 3)
        self.assertIn(P.CODE_WORKTREE_OWNED_STATE, self.codes(plan))

    def test_a_clean_unlocked_sibling_worktree_is_reported_not_refused(self) -> None:
        # The negative case matters as much as the positive one: a repository that
        # simply HAS worktrees must stay plannable, or the tool is unusable in the
        # repository it was written for.
        sibling = self.tmp / "sibling"
        self.git("worktree", "add", "-q", "-b", "sibling", str(sibling), "HEAD")
        completed, plan = self.plan("--repo", "public", "--fetch")
        self.assertEqual(completed.returncode, 0, completed.stderr.decode())
        paths = {w["path"] for w in plan["repos"]["public"]["worktrees"]}
        self.assertIn(str(sibling), paths)

    def test_a_missing_base_ref_refuses(self) -> None:
        completed, plan = self.plan("--repo", "public", "--base", "origin/nonexistent")
        self.assertEqual(completed.returncode, 3)
        self.assertIn(P.CODE_BASE_REF_MISSING, self.codes(plan))

    def test_a_repo_with_no_remote_refuses(self) -> None:
        self.git("remote", "remove", "origin")
        completed, plan = self.plan("--repo", "public")
        self.assertEqual(completed.returncode, 3)
        self.assertIn(P.CODE_REMOTE_MISSING, self.codes(plan))

    def test_a_failed_fetch_is_a_refusal_never_stale(self) -> None:
        self.git("remote", "set-url", "origin", str(self.tmp / "gone.git"))
        completed, plan = self.plan("--repo", "public", "--fetch")
        self.assertEqual(completed.returncode, 3, completed.stderr.decode())
        self.assertIn(P.CODE_FETCH_FAILED, self.codes(plan))
        self.assertFalse(plan["executable"])
        # It is also not silently promoted to fresh.
        self.assertEqual(plan["remote_knowledge"]["state"], "stale")

    def test_a_symlink_that_escapes_the_repository_refuses(self) -> None:
        (self.repo / "escape").symlink_to(self.tmp / "home")
        completed, plan = self.plan("--repo", "public", "--fetch")
        self.assertEqual(completed.returncode, 3)
        self.assertIn(P.CODE_SYMLINK_ESCAPES, self.codes(plan))


# ── fail-closed: ignored destinations, prerequisites, destinations ───────────
class FailClosedDataTests(PlannerFixture):

    def test_an_ignored_destination_conflict_refuses(self) -> None:
        self.write("companies/acme/research/dossier.md", "dossier\n")
        self.write("me/interviews/companies/acme/research/dossier.md", "OTHER\n")
        completed, plan = self.plan("--repo", "public", "--fetch")
        self.assertEqual(completed.returncode, 3)
        self.assertIn(P.CODE_IGNORED_CONFLICT, self.codes(plan))
        # The source is still on disk, byte for byte: nothing here deletes or
        # overwrites owner data, and no step proposes it either.
        self.assertEqual(
            (self.repo / "companies/acme/research/dossier.md").read_text(), "dossier\n")
        self.assertEqual(
            (self.repo / "me/interviews/companies/acme/research/dossier.md").read_text(),
            "OTHER\n")
        ops = {step["op"] for step in plan["steps"]}
        self.assertNotIn("copy-ignored", ops)

    def test_an_identical_ignored_destination_needs_no_action(self) -> None:
        self.write("companies/acme/research/dossier.md", "dossier\n")
        self.write("me/interviews/companies/acme/research/dossier.md", "dossier\n")
        completed, plan = self.plan("--repo", "public", "--fetch")
        self.assertEqual(completed.returncode, 0, completed.stderr.decode())
        dirty = {d["path"]: d for d in plan["repos"]["public"]["dirty"]}
        entry = dirty["companies/acme/research/dossier.md"]
        self.assertEqual(entry["action"], "none")
        self.assertTrue(entry["destination_bytes_equal"])

    def test_an_ignored_file_that_must_be_copied_gets_a_create_only_step(self) -> None:
        self.write("companies/acme/research/dossier.md", "dossier\n")
        completed, plan = self.plan("--repo", "public", "--fetch")
        self.assertEqual(completed.returncode, 0, completed.stderr.decode())
        copy = [s for s in plan["steps"] if s["op"] == "copy-ignored"]
        self.assertEqual(len(copy), 1)
        self.assertEqual(copy[0]["kind"], "mechanical")
        self.assertEqual([p["kind"] for p in copy[0]["preconditions"]],
                         ["destination-absent"])
        flat = " ".join(" ".join(argv) for argv in copy[0]["argv"])
        self.assertIn("--copy", flat)
        # Never a delete, never an overwrite: the ONLY verbs allowed near an
        # ignored source.
        for forbidden in ("rm ", "--force", "mv ", "git clean"):
            self.assertNotIn(forbidden, flat)

    def test_an_unreachable_prerequisite_refuses(self) -> None:
        self.write("unreached.md", "x\n")
        unreachable = self.commit("a commit that never merged")
        completed, plan = self.plan("--repo", "public", "--fetch",
                                    "--prereq", f"public:{unreachable}")
        self.assertEqual(completed.returncode, 3)
        self.assertIn(P.CODE_PREREQ_UNREACHABLE, self.codes(plan))
        self.assertFalse(plan["prerequisites"][0]["reachable_from_base"])

    def test_a_reachable_prerequisite_is_recorded_and_does_not_block(self) -> None:
        completed, plan = self.plan("--repo", "public", "--fetch",
                                    "--prereq", f"public:{self.merged}")
        self.assertEqual(completed.returncode, 0, completed.stderr.decode())
        self.assertEqual(len(plan["prerequisites"]), 1)
        self.assertTrue(plan["prerequisites"][0]["reachable_from_base"])
        self.assertEqual(plan["prerequisites"][0]["oid"], self.merged)

    def test_a_json_out_inside_the_repo_outside_local_is_refused(self) -> None:
        target = self.repo / "docs" / "plan.json"
        completed, _ = self.plan("--repo", "public", "--fetch",
                                 "--json-out", str(target))
        self.assertEqual(completed.returncode, 3)
        self.assertIn(P.CODE_JSON_OUT_TRACKED, completed.stdout.decode())
        self.assertFalse(target.exists(), "the refused destination must not be written")

    def test_a_json_out_under_local_is_accepted(self) -> None:
        target = self.repo / "local" / "cutover" / "plan.json"
        completed, _ = self.plan("--repo", "public", "--fetch",
                                 "--json-out", str(target))
        self.assertEqual(completed.returncode, 0, completed.stderr.decode())
        self.assertTrue(target.is_file())


# ── fail-closed: configuration + the overlay ─────────────────────────────────
class StubConfig:
    """A stand-in for automation/shared/config.py — never the real loader."""

    EXAMPLE_CONFIG = Path("/nowhere/config.example.yaml")

    def __init__(self, *, active: Path, mounted: bool = True,
                 overlay: Path | None = None, error: Exception | None = None) -> None:
        self._active = active
        self._mounted = mounted
        self._overlay = overlay or Path("/nowhere/overlay")
        self._error = error

    def config_path(self) -> Path:
        if self._error is not None:
            raise self._error
        return self._active

    def overlay_mounted(self) -> bool:
        return self._mounted

    def overlay_root(self) -> Path:
        return self._overlay


class ConfigBlockerTests(unittest.TestCase):
    """Driven through a stub so no test can read the developer's real config."""

    def use(self, stub: StubConfig) -> None:
        saved = P.config
        P.config = stub
        self.addCleanup(lambda: setattr(P, "config", saved))

    def test_an_unresolvable_config_refuses(self) -> None:
        self.use(StubConfig(active=Path("/x"), error=RuntimeError("no config.yaml")))
        blocking, overlay = P.config_blockers(("private",))
        self.assertEqual([b.code for b in blocking], [P.CODE_CONFIG_UNRESOLVED])
        self.assertIsNone(overlay)

    def test_the_example_fallback_refuses_when_private_is_in_scope(self) -> None:
        self.use(StubConfig(active=StubConfig.EXAMPLE_CONFIG))
        blocking, overlay = P.config_blockers(("private", "public"))
        self.assertEqual([b.code for b in blocking], [P.CODE_CONFIG_EXAMPLE])
        self.assertIsNone(overlay)

    def test_the_example_fallback_is_fine_for_public_only(self) -> None:
        self.use(StubConfig(active=StubConfig.EXAMPLE_CONFIG))
        self.assertEqual(P.config_blockers(("public",)), ([], None))

    def test_an_unmounted_overlay_refuses(self) -> None:
        self.use(StubConfig(active=Path("/real/config.yaml"), mounted=False))
        blocking, _ = P.config_blockers(("private",))
        self.assertEqual([b.code for b in blocking], [P.CODE_OVERLAY_NOT_MOUNTED])

    def test_an_overlay_that_is_not_a_repository_refuses(self) -> None:
        tmp = Path(tempfile.mkdtemp(prefix="cutover-overlay-")).resolve()
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        self.use(StubConfig(active=Path("/real/config.yaml"), overlay=tmp))
        blocking, _ = P.config_blockers(("private",))
        self.assertEqual([b.code for b in blocking], [P.CODE_OVERLAY_NOT_A_REPO])

    def test_every_refusal_code_is_declared(self) -> None:
        self.assertEqual(len(P.BLOCKING_CODES), 18)
        self.assertEqual(len(set(P.BLOCKING_CODES)), 18)


class OverlayScopeTests(PlannerFixture):

    def test_a_mounted_overlay_is_inventoried(self) -> None:
        self.make_overlay()
        completed, plan = self.plan("--repo", "private", "--fetch")
        self.assertEqual(completed.returncode, 0, completed.stderr.decode())
        self.assertIn("private", plan["repos"])
        self.assertNotIn("public", plan["repos"])
        self.assertEqual(plan["repos"]["private"]["branch"], "main")

    def test_a_missing_overlay_refuses(self) -> None:
        completed, plan = self.plan("--repo", "private", "--fetch")
        self.assertEqual(completed.returncode, 3)
        self.assertIn(P.CODE_OVERLAY_NOT_MOUNTED, self.codes(plan))

    def test_an_overlay_tracked_as_a_gitlink_refuses(self) -> None:
        overlay = self.make_overlay(self.repo / "overlay")
        self.config_path = self.write_config(overlay)
        self.git("add", "overlay")
        self.git("commit", "-qm", "track the overlay as a gitlink")
        completed, plan = self.plan("--repo", "both", "--fetch")
        self.assertEqual(completed.returncode, 3, completed.stderr.decode())
        self.assertIn(P.CODE_OVERLAY_IS_GITLINK, self.codes(plan))

    def test_the_remote_url_is_digested_never_printed(self) -> None:
        completed, plan = self.plan("--repo", "public", "--fetch")
        self.assertEqual(completed.returncode, 0, completed.stderr.decode())
        remote = plan["repos"]["public"]["remote"]
        self.assertTrue(remote["url_digest"].startswith("sha256:"))
        self.assertNotIn(str(self.origin), json.dumps(plan))


# ── the read-only promise ────────────────────────────────────────────────────
class ReadOnlyRunTests(PlannerFixture):

    def snapshot(self) -> dict:
        objects = sorted(
            (str(p.relative_to(self.repo)), p.stat().st_size)
            for p in (self.repo / ".git/objects").rglob("*") if p.is_file())
        index = self.repo / ".git/index"
        return {
            "status": self.git("status", "--porcelain=v2", "-z",
                               "--untracked-files=all", "--ignored=traditional"),
            "head": self.git("rev-parse", "HEAD"),
            "refs": self.git("rev-parse", "--all"),
            "objects": objects,
            "object_count": len(objects),
            "index": hashlib.sha256(index.read_bytes()).hexdigest()
            if index.is_file() else None,
        }

    def test_a_full_run_leaves_the_repository_byte_identical(self) -> None:
        self.write("interviews/calendar.md", CALENDAR_OLD + "- local todo\n")
        self.write("companies/acme/notes.md", "acme notes\nlocal\n")
        self.write("companies/acme/research/dossier.md", "dossier\n")
        before = self.snapshot()
        completed, plan = self.plan("--repo", "public", "--fetch")
        self.assertIn(completed.returncode, (0, 1), completed.stderr.decode())
        self.assertTrue(plan["repos"]["public"]["dirty"])
        after = self.snapshot()
        self.assertEqual(before["head"], after["head"])
        self.assertEqual(before["refs"], after["refs"])
        self.assertEqual(before["status"], after["status"])
        self.assertEqual(before["object_count"], after["object_count"])
        self.assertEqual(before["objects"], after["objects"])
        self.assertEqual(before["index"], after["index"])

    def test_fetch_writes_only_remote_tracking_refs(self) -> None:
        before_local = self.git("for-each-ref", "--format=%(refname) %(objectname)",
                                "refs/heads")
        self.plan("--repo", "public", "--fetch")
        after_local = self.git("for-each-ref", "--format=%(refname) %(objectname)",
                               "refs/heads")
        self.assertEqual(before_local, after_local)

    def test_the_git_wrapper_refuses_a_fetch_without_authorisation(self) -> None:
        with self.assertRaises(CD.GitError):
            CD.ReadOnlyGit(self.repo).run("fetch", "origin")


# ── the plan document ────────────────────────────────────────────────────────
class PlanDocumentTests(PlannerFixture):

    def test_two_runs_over_identical_state_are_byte_identical(self) -> None:
        self.write("interviews/calendar.md", CALENDAR_OLD + "- local todo\n")
        first_out = self.tmp / "first.json"
        second_out = self.tmp / "second.json"
        self.plan("--repo", "public", json_out=first_out)
        self.plan("--repo", "public", json_out=second_out)

        def normalise(path: Path) -> str:
            payload = json.loads(path.read_text())
            run_id = payload["run_id"]
            text = path.read_text().replace(run_id, "<RUN_ID>")
            reloaded = json.loads(text)
            reloaded["generated_at"] = "<GENERATED_AT>"
            return P.dump_plan(reloaded)

        self.assertEqual(normalise(first_out), normalise(second_out))

    def test_the_plan_matches_the_declared_schema_and_enum_domains(self) -> None:
        self.write("interviews/calendar.md", CALENDAR_OLD + "- local todo\n")
        self.write("companies/acme/research/dossier.md", "dossier\n")
        self.write("companies/acme/notes.md", "acme notes\nlocal\n")
        _, plan = self.plan("--repo", "public", "--fetch")
        self.assertEqual(set(plan), PLAN_KEYS)
        self.assertEqual(plan["schema"], "cutover-plan/v1")
        self.assertEqual(plan["validation_profile"], "cutover")
        self.assertIn(plan["remote_knowledge"]["state"], P.REMOTE_STATES)
        self.assertIs(plan["executable"], plan["exit_code"] == 0)
        self.assertEqual(set(plan["generator"]), {"argv", "git_version", "tool"})
        for step in plan["steps"]:
            self.assertIn(step["kind"], P.STEP_KINDS)
            self.assertIn(step["op"], P.STEP_OPS)
            self.assertIn(step["repo"], P.REPO_NAMES)
        for item in plan["blocking"]:
            self.assertIn(item["code"], P.BLOCKING_CODES)
        for entry in plan["repos"]["public"]["dirty"]:
            self.assertEqual(set(entry), DIRTY_KEYS)
            self.assertIn(entry["verdict"], CD.VERDICTS)
            self.assertIn(entry["action"], CD.ACTIONS)
            self.assertIn(entry["residual_after_link_rebase"], CD.RESIDUALS)
        # Every verdict the fixture is built to produce is actually produced.
        verdicts = {e["verdict"] for e in plan["repos"]["public"]["dirty"]}
        self.assertIn(CD.VERDICT_CONTENT_DIVERGENT, verdicts)
        self.assertIn(CD.VERDICT_RENAMED, verdicts)
        self.assertIn(CD.VERDICT_IGNORED, verdicts)

    def test_the_generator_argv_never_carries_the_json_out_path(self) -> None:
        secret = self.tmp / "sensitive-destination.json"
        _, plan = self.plan("--repo", "public", "--fetch", json_out=secret)
        self.assertNotIn(str(secret), json.dumps(plan["generator"]))
        self.assertEqual(plan["generator"]["argv"],
                         ["--repo", "public", "--base", "origin/main", "--fetch"])

    def test_the_session_id_defaults_to_the_environment(self) -> None:
        _, plan = self.plan("--repo", "public",
                            env_extra={"JOBHUNT_SESSION_ID": "sess-123"})
        self.assertEqual(plan["session_id"], "sess-123")

    def test_no_step_proposes_a_deletion_a_bypass_or_a_publish_command(self) -> None:
        self.write("interviews/calendar.md", CALENDAR_OLD + "- local todo\n")
        self.write("companies/acme/notes.md", "acme notes\nlocal\n")
        self.write("companies/acme/research/dossier.md", "dossier\n")
        _, plan = self.plan("--repo", "public", "--fetch")
        flat = json.dumps(plan["steps"])
        for forbidden in ("--no-verify", "--skip-checks", "git clean", "\"rm\"",
                          "worktree\", \"remove", "branch\", \"-D",
                          "update-ref\", \"-d", "\"push\"", "\"gh\"", "restore"):
            self.assertNotIn(forbidden, flat, forbidden)
        # Publication is a handoff to the runbook, never a command.
        publish = [s for s in plan["steps"] if s["op"] == "publish"]
        self.assertTrue(publish)
        for step in publish:
            self.assertEqual(step["kind"], "handoff")
            self.assertIsNone(step["argv"])
            self.assertEqual(step["handoff"]["skill"], P.PUBLICATION_SKILL)

    def test_every_mutating_step_names_a_recovery_ref_before_it_runs(self) -> None:
        self.write("companies/acme/notes.md", "acme notes\nlocal\n")
        _, plan = self.plan("--repo", "public", "--fetch")
        mutating = [s for s in plan["steps"]
                    if s["kind"] == "mechanical" and s["op"] in ("checkpoint", "replay")]
        self.assertTrue(mutating)
        for step in mutating:
            self.assertTrue(step["recovery_ref"].startswith("refs/cutover/"))
            self.assertEqual(step["recovery_argv"][:3], ["git", "reset", "--hard"])
            kinds = {p["kind"] for p in step["preconditions"]}
            self.assertEqual(kinds, {"head-oid", "no-in-progress-op",
                                     "worktree-set-digest", "dirty-blob-digest"})

    def test_the_rollup_never_folds_a_path_that_needs_copying(self) -> None:
        """The rollup exists to shrink noise, never to hide the copy case.

        Against the real repositories one entry per ignored path produced a
        72 MB plan — unreadable, so useless as a handoff. Only ignored paths
        with NO merged-layout counterpart and no blocking are folded; the
        ignored path that DOES have a counterpart is the whole reason this
        tool exists and must keep its full entry.
        """
        self.write("companies/acme/research/dossier.md", "dossier\n")   # has a counterpart
        self.write("scratch/junk/a.tmp", "x\n")                          # has none
        self.write("scratch/junk/b.tmp", "y\n")
        completed, plan = self.plan("--repo", "public", "--fetch")
        self.assertIn(completed.returncode, (0, 1), completed.stderr.decode())

        public = plan["repos"]["public"]
        emitted = {d["path"] for d in public["dirty"]}
        self.assertIn("companies/acme/research/dossier.md", emitted)
        self.assertNotIn("scratch/junk/a.tmp", emitted)

        rolled = public["dirty_rolled_up"]
        # Nothing is lost: every path is either emitted or counted.
        self.assertEqual(public["dirty_total"],
                         len(public["dirty"]) + rolled["paths"])
        self.assertEqual(rolled["zones_omitted"], 0)

    def test_full_json_restores_every_path(self) -> None:
        self.write("scratch/junk/a.tmp", "x\n")
        self.write("scratch/junk/b.tmp", "y\n")
        completed, plan = self.plan("--repo", "public", "--fetch", "--full-json")
        self.assertIn(completed.returncode, (0, 1), completed.stderr.decode())
        public = plan["repos"]["public"]
        self.assertEqual(len(public["dirty"]), public["dirty_total"])
        self.assertEqual(public["dirty_rolled_up"], {})
        emitted = {d["path"] for d in public["dirty"]}
        self.assertIn("scratch/junk/a.tmp", emitted)

    def test_a_blocking_ignored_path_is_never_rolled_up(self) -> None:
        self.write("companies/acme/research/dossier.md", "dossier\n")
        self.write("me/interviews/companies/acme/research/dossier.md", "OTHER\n")
        completed, plan = self.plan("--repo", "public", "--fetch")
        self.assertEqual(completed.returncode, 3)
        emitted = {d["path"] for d in plan["repos"]["public"]["dirty"]}
        self.assertIn("companies/acme/research/dossier.md", emitted)

    def test_explain_prints_the_evidence_chain_for_one_path(self) -> None:
        self.write("interviews/calendar.md", CALENDAR_OLD + "- local todo\n")
        completed, _ = self.plan("--repo", "public",
                                 "--explain", "interviews/calendar.md")
        self.assertEqual(completed.returncode, 0, completed.stderr.decode())
        text = completed.stdout.decode()
        self.assertIn("me/interviews/calendar.md", text)
        self.assertIn("residual", text)
        self.assertIn("hash-object, no -w", text)

    def test_explain_refuses_a_path_it_cannot_find(self) -> None:
        completed, _ = self.plan("--repo", "public", "--explain", "no/such/file.md")
        self.assertEqual(completed.returncode, 3)

    def test_explain_still_refuses_when_the_inventory_is_blocked(self) -> None:
        """--explain is a narrower VIEW, never a lighter contract.

        It used to return print_explanation's own code and discard the blocking
        list built moments earlier, so every per-path refusal — including the
        one printed in that very output — exited 0. Exit 0 asserts "blocking is
        empty"; a caller branching on it would act on a refused plan.
        """
        self.write("mystery.txt", "no rename evidence for this one\n")
        blocked, _ = self.plan("--repo", "public", "--fetch")
        self.assertEqual(blocked.returncode, 3, "precondition: the tree refuses")

        completed, _ = self.plan("--repo", "public", "--fetch",
                                 "--explain", "mystery.txt")
        text = completed.stdout.decode()
        self.assertIn("BLOCKING", text)
        self.assertEqual(completed.returncode, 3,
                         "--explain must not downgrade a refusal to executable")

    def test_an_unexpected_crash_refuses_rather_than_exiting_one(self) -> None:
        """Exit 1 means "readable plan, needs judgement" — a crash is not that.

        Worker exceptions re-raised out of the thread pool reached the bare
        ``raise SystemExit(main())`` and became Python's default exit 1, so a
        script branching on ``3 == refused`` read a traceback as a usable plan.
        """
        argv = [sys.executable, str(_CUTOVER_DIR / "plan_cutover.py"),
                "--public-root", str(self.tmp / "does-not-exist"), "--repo", "public"]
        completed = subprocess.run(argv, cwd=str(self.tmp), env=self.env,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   check=False)
        self.assertEqual(completed.returncode, 3, completed.stderr.decode())
        self.assertIn("REFUSED", completed.stdout.decode())


# ── naming discipline + the routed doc (decision 1 / decision 14) ────────────
class DisambiguationTests(unittest.TestCase):

    def test_the_help_text_says_this_is_not_the_process_layer_gate(self) -> None:
        completed = subprocess.run(
            [sys.executable, str(_CUTOVER_DIR / "plan_cutover.py"), "--help"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
        self.assertEqual(completed.returncode, 0, completed.stderr.decode())
        # argparse re-wraps the description, so compare on collapsed whitespace.
        rendered = " ".join(completed.stdout.decode().split())
        self.assertIn(" ".join(P.DISAMBIGUATION_LINE.split()), rendered)

    def test_the_handbook_doc_carries_the_same_line(self) -> None:
        self.assertTrue(HANDBOOK_DOC.is_file(), f"{HANDBOOK_DOC} must exist")
        collapsed = " ".join(HANDBOOK_DOC.read_text().split())
        self.assertIn(" ".join(P.DISAMBIGUATION_LINE.split()), collapsed)

    def test_the_handbook_doc_states_that_no_executor_ships(self) -> None:
        text = HANDBOOK_DOC.read_text()
        self.assertNotIn("apply_cutover.py", text)
        self.assertIn("performed by the agent", text.lower())

    def test_the_table_warns_before_it_names_an_overlay_path(self) -> None:
        self.assertIn("never paste it into a public PR", P.TABLE_PRIVACY_WARNING)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
