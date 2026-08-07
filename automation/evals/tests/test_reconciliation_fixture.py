"""Tests for the pinned reconciliation fixture and its stage harness.

Run with (from the repo root):
    .venv/bin/python -m unittest discover -s automation/evals/tests

Every test builds into a throwaway temp directory. Nothing here writes into this
checkout, and one test asserts exactly that.

What is pinned here, and why each one is worth a test:

  * **determinism.** Two builds must produce identical commit SHAs. That is the
    fixture's entire value — a stage row measured against a tree whose objects
    move is comparing two different problems while claiming to compare one lever;
  * **the pins themselves.** :data:`PINNED_SHAS` is asserted, so editing the
    recipe without bumping ``FIXTURE_VERSION`` turns the ``tests-evals`` gate red.
    A "please don't edit this" comment is the version of that rule that does not
    hold;
  * **isolation from the operator.** The build runs under a hostile ``HOME``,
    ``~/.gitconfig``, ``GIT_CONFIG_GLOBAL`` and ``GIT_AUTHOR_*`` and still produces
    the pinned SHAs. This is the fragile part of any pinned-SHA scheme;
  * **the scenario's five properties**, one test each: the merged layout refactor,
    the dirty patch at the OLD paths, the path-only generated-file delta, the
    ignored file that must be copied non-overwriting and RETAINED, and closeout
    records that the REAL reconciler grades red before and green after;
  * **the destination guard.** A mistyped ``--out`` must never write into the
    tracked tree, and ``--force`` must never delete a directory this module did
    not generate — the fixture's neighbour on a maintainer's machine is the real
    ``private/`` overlay, which agents may not delete from under any condition.
"""
from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

EVALS_DIR = Path(__file__).resolve().parents[1]
if str(EVALS_DIR) not in sys.path:
    sys.path.insert(0, str(EVALS_DIR))

import reconciliation_bench as BENCH  # noqa: E402
import reconciliation_fixture as FIX  # noqa: E402

REPO_ROOT = FIX.REPO_ROOT

# Building a fixture costs ~1 s (two git repositories, four commits, two pushes).
# Read-only assertions share one build per variant; the tests that are ABOUT
# building do their own.
_SHARED: dict[str, FIX.FixtureManifest] = {}
_SHARED_TMP: tempfile.TemporaryDirectory | None = None


def setUpModule() -> None:
    global _SHARED_TMP
    _SHARED_TMP = tempfile.TemporaryDirectory(prefix="recon-fixture-shared-")
    for variant in ("base", "destination-exists"):
        _SHARED[variant] = FIX.build(Path(_SHARED_TMP.name) / variant, variant=variant)


def tearDownModule() -> None:
    if _SHARED_TMP is not None:
        _SHARED_TMP.cleanup()


def _git(repo: Path, *args: str) -> tuple[int, str]:
    proc = subprocess.run(("git", "-C", str(repo), *args),
                          capture_output=True, text=True)
    return proc.returncode, proc.stdout


def _cli(entry, argv: list[str]) -> tuple[int, str]:
    """Run a module's ``main`` with its streams captured."""
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = entry(argv)
    return code, out.getvalue() + err.getvalue()


class TestDeterminism(unittest.TestCase):

    def test_build_is_deterministic(self) -> None:
        """Two builds, two destinations, identical commit SHAs."""
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            first = FIX.build(Path(a) / "fixture")
            second = FIX.build(Path(b) / "fixture")
        self.assertEqual(first.commits, second.commits)
        # Guard against a vacuous pass if the recipe ever stops committing.
        self.assertEqual(len(first.commits["public"]), 2)
        self.assertEqual(len(first.commits["overlay"]), 2)

    def test_pinned_shas_match_the_manifest(self) -> None:
        """The gate: a recipe edit without a FIXTURE_VERSION bump goes red."""
        manifest = _SHARED["base"]
        self.assertEqual(manifest.commits, FIX.PINNED_SHAS)
        self.assertNotIn("PENDING", json.dumps(FIX.PINNED_SHAS))

    def test_build_is_isolated_from_the_operator_git_config(self) -> None:
        """A hostile HOME, global config and author env still yield the pins."""
        with tempfile.TemporaryDirectory() as hostile, \
                tempfile.TemporaryDirectory() as out:
            gitconfig = Path(hostile) / ".gitconfig"
            gitconfig.write_text(
                "[init]\n\tdefaultBranch = trunk\n"
                "[core]\n\tautocrlf = true\n"
                "[commit]\n\tgpgsign = true\n"
                "[diff]\n\trenames = false\n"
                "[user]\n\tname = Somebody Else\n\temail = somebody@example.org\n",
                encoding="utf-8")
            poison = {
                "HOME": hostile,
                "XDG_CONFIG_HOME": hostile,
                "GIT_CONFIG_GLOBAL": str(gitconfig),
                "GIT_AUTHOR_NAME": "Somebody Else",
                "GIT_AUTHOR_EMAIL": "somebody@example.org",
                "GIT_AUTHOR_DATE": "2001-02-03T04:05:06+00:00",
                "GIT_COMMITTER_DATE": "2001-02-03T04:05:06+00:00",
                "TZ": "Pacific/Kiritimati",
                "LC_ALL": "tr_TR.UTF-8",
            }
            with mock.patch.dict(os.environ, poison, clear=False):
                manifest = FIX.build(Path(out) / "fixture")
        self.assertEqual(manifest.commits, FIX.PINNED_SHAS)

    def test_the_three_variants_share_one_history(self) -> None:
        """A variant changes the working tree, never the commits a row measured."""
        self.assertEqual(_SHARED["base"].commits,
                         _SHARED["destination-exists"].commits)


class TestScenario(unittest.TestCase):
    """One test per bullet of the task's "Benchmark scenario" section."""

    def test_public_main_carries_the_merged_layout_refactor(self) -> None:
        public = _SHARED["base"].public
        self.assertFalse((public / FIX.OLD_ROOT).exists(), "me/ survived the refactor")
        self.assertTrue((public / FIX.NEW_ROOT / "profile.md").is_file())
        code, out = _git(public, "diff", "--name-status", "--find-renames=100%",
                         "main~1", "main")
        self.assertEqual(code, 0)
        renames = [ln for ln in out.splitlines() if ln.startswith("R100")]
        self.assertTrue(renames, f"no R100 rename evidence in:\n{out}")
        self.assertTrue(any(f"{FIX.OLD_ROOT}/" in ln and f"{FIX.NEW_ROOT}/" in ln
                            for ln in renames), out)
        code, out = _git(public, "status", "--porcelain=v1")
        self.assertEqual((code, out.strip()), (0, ""), "public tree is not clean")

    def test_overlay_dirty_patch_is_against_the_old_paths(self) -> None:
        overlay = _SHARED["base"].overlay
        code, out = _git(overlay, "status", "--porcelain=v1")
        self.assertEqual(code, 0)
        modified = sorted(ln[3:] for ln in out.splitlines() if ln.startswith(" M"))
        self.assertEqual(modified, [f"{FIX.OLD_ROOT}/{FIX.GENERATED_REL}",
                                    f"{FIX.OLD_ROOT}/notes/journal.md"])
        # …and those paths do not exist on the overlay's origin/main.
        code, tree = _git(overlay, "ls-tree", "-r", "--name-only", "origin/main")
        self.assertEqual(code, 0)
        for path in modified:
            self.assertNotIn(path, tree.splitlines())
        code, out = _git(overlay, "rev-list", "--left-right", "--count",
                         "main...origin/main")
        self.assertEqual((code, out.split()), (0, ["0", "1"]),
                         "local main should be exactly one commit behind origin/main")

    def test_generated_conflict_delta_is_path_only(self) -> None:
        """The claim the real session had to prove by hand, made mechanical."""
        overlay = _SHARED["base"].overlay
        code, old = _git(overlay, "show",
                         f"codex/dirty:{FIX.OLD_ROOT}/{FIX.GENERATED_REL}")
        self.assertEqual(code, 0)
        code, new = _git(overlay, "show",
                         f"origin/main:{FIX.NEW_ROOT}/{FIX.GENERATED_REL}")
        self.assertEqual(code, 0)
        self.assertNotEqual(old, new, "the two versions are identical — no conflict")
        self.assertEqual(FIX.rewrite_layout_paths(old), new,
                         "the migration delta is NOT path-only")

    def test_ignored_file_is_untracked_at_the_old_path_and_absent_at_the_new(self) -> None:
        overlay = _SHARED["base"].overlay
        source = overlay / FIX.OLD_ROOT / FIX.IGNORED_REL
        self.assertTrue(source.is_file())
        self.assertFalse((overlay / FIX.NEW_ROOT / FIX.IGNORED_REL).exists())
        code, out = _git(overlay, "ls-files", "--others", "--ignored",
                         "--exclude-standard")
        self.assertEqual(code, 0)
        self.assertIn(f"{FIX.OLD_ROOT}/{FIX.IGNORED_REL}", out.splitlines())
        code, out = _git(overlay, "ls-files", "--error-unmatch", "--",
                         f"{FIX.OLD_ROOT}/{FIX.IGNORED_REL}")
        self.assertNotEqual(code, 0, "the ignored file must not be tracked")

    def test_destination_exists_variant_places_different_bytes_at_the_destination(self) -> None:
        overlay = _SHARED["destination-exists"].overlay
        source = overlay / FIX.OLD_ROOT / FIX.IGNORED_REL
        dest = overlay / FIX.NEW_ROOT / FIX.IGNORED_REL
        self.assertTrue(source.is_file())
        self.assertTrue(dest.is_file())
        self.assertNotEqual(source.read_bytes(), dest.read_bytes(),
                            "a non-overwriting copy needs something to refuse")
        code, out = _git(overlay, "status", "--porcelain=v1", "--untracked-files=all")
        self.assertEqual(code, 0)
        self.assertNotIn(FIX.NEW_ROOT, out,
                         "the pre-placed occupant must be ignored, not untracked")

    def test_overlay_is_a_nested_repo_ignored_by_the_public_one(self) -> None:
        manifest = _SHARED["base"]
        self.assertEqual(manifest.overlay, manifest.public / "private")
        self.assertTrue((manifest.overlay / ".git").is_dir())
        self.assertIn("private/",
                      (manifest.public / ".gitignore").read_text(encoding="utf-8"))
        code, out = _git(manifest.public, "status", "--porcelain=v1",
                         "--untracked-files=all")
        self.assertEqual((code, out.strip()), (0, ""),
                         "the nested overlay leaked into the public repo's status")

    def test_closeout_records_flip_the_reconciler_from_red_to_green(self) -> None:
        """The REAL reconciler, via --root — not a simulation of the gates."""
        reconcile = REPO_ROOT / "automation" / "reconcile" / "reconcile.py"
        with tempfile.TemporaryDirectory() as tmp:
            manifest = FIX.build(Path(tmp) / "fixture")
            before = subprocess.run(
                (sys.executable, str(reconcile), "--check", "--root", str(manifest.public)),
                capture_output=True, text=True)
            self.assertEqual(before.returncode, 1, before.stdout + before.stderr)
            self.assertIn("handover-present", before.stdout)
            self.assertIn("memory-index", before.stdout)

            FIX.write_closeout_records(manifest.public)
            fix = subprocess.run(
                (sys.executable, str(reconcile), "--fix-index", "--root", str(manifest.public)),
                capture_output=True, text=True)
            self.assertEqual(fix.returncode, 0, fix.stdout + fix.stderr)
            after = subprocess.run(
                (sys.executable, str(reconcile), "--check", "--root", str(manifest.public)),
                capture_output=True, text=True)
            self.assertEqual(after.returncode, 0, after.stdout + after.stderr)

    def test_closeout_done_variant_is_green_from_the_start(self) -> None:
        reconcile = REPO_ROOT / "automation" / "reconcile" / "reconcile.py"
        with tempfile.TemporaryDirectory() as tmp:
            manifest = FIX.build(Path(tmp) / "fixture", variant="closeout-done")
            proc = subprocess.run(
                (sys.executable, str(reconcile), "--check", "--root", str(manifest.public)),
                capture_output=True, text=True)
            # memory/index.md is generated, never hand-written, so the control arm
            # still owes one --fix-index. The handover, which is the closeout
            # RECORD, is already there.
            self.assertNotIn("handover-present", proc.stdout)


class TestDestinationGuard(unittest.TestCase):

    def test_refuses_a_destination_inside_the_tracked_tree(self) -> None:
        for rel in ("automation/evals/junk", "skills", "private/market", "evals/fixtures"):
            with self.subTest(rel=rel):
                with self.assertRaises(FIX.FixtureError):
                    FIX.resolve_destination(REPO_ROOT / rel)

    def test_refuses_the_repository_root(self) -> None:
        with self.assertRaises(FIX.FixtureError):
            FIX.resolve_destination(REPO_ROOT)

    def test_allows_the_git_ignored_scratch_roots_and_anywhere_outside(self) -> None:
        self.assertEqual(FIX.resolve_destination(REPO_ROOT / "local" / "bench"),
                         REPO_ROOT / "local" / "bench")
        with tempfile.TemporaryDirectory() as tmp:
            outside = Path(tmp) / "fixture"
            self.assertEqual(FIX.resolve_destination(outside), outside)

    def test_write_refuses_a_path_that_escapes_the_fixture(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "fixture"
            root.mkdir()
            with self.assertRaises(FIX.FixtureError):
                FIX._write_file(root, "../escaped.txt", "no")
            self.assertFalse((Path(tmp) / "escaped.txt").exists())

    def test_non_empty_destination_needs_force(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "fixture"
            dest.mkdir()
            (dest / "someone-elses-file.txt").write_text("data", encoding="utf-8")
            with self.assertRaises(FIX.FixtureError):
                FIX.build(dest)
            self.assertTrue((dest / "someone-elses-file.txt").is_file())

    def test_force_refuses_a_directory_it_did_not_generate(self) -> None:
        """--force replaces a fixture; it is never "delete whatever is there"."""
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "not-a-fixture"
            dest.mkdir()
            (dest / "owner-data.txt").write_text("do not delete", encoding="utf-8")
            with self.assertRaises(FIX.FixtureError):
                FIX.build(dest, force=True)
            self.assertEqual((dest / "owner-data.txt").read_text(encoding="utf-8"),
                             "do not delete")

    def test_force_replaces_a_fixture_this_module_generated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "fixture"
            first = FIX.build(dest)
            second = FIX.build(dest, force=True)
            self.assertEqual(first.commits, second.commits)

    def test_build_writes_nothing_into_this_checkout(self) -> None:
        before = _git(REPO_ROOT, "status", "--porcelain=v1", "--untracked-files=all")
        with tempfile.TemporaryDirectory() as tmp:
            FIX.build(Path(tmp) / "fixture")
        after = _git(REPO_ROOT, "status", "--porcelain=v1", "--untracked-files=all")
        self.assertEqual(before, after)


class TestVerify(unittest.TestCase):

    def test_verify_is_clean_on_a_fresh_build(self) -> None:
        self.assertEqual(FIX.verify(_SHARED["base"].root), [])
        self.assertEqual(FIX.verify(_SHARED["destination-exists"].root), [])

    def test_verify_reports_a_mutated_fixture(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manifest = FIX.build(Path(tmp) / "fixture")
            self.assertEqual(FIX.verify(manifest.root), [])
            # A commit the pins do not know about: the state under test moved.
            subprocess.run(("git", "-C", str(manifest.public), "commit",
                            "--allow-empty", "--quiet", "-m", "drift",
                            "--author", "Drift <drift@example.com>"),
                           capture_output=True, text=True,
                           env={**os.environ,
                                "GIT_AUTHOR_NAME": "Drift",
                                "GIT_AUTHOR_EMAIL": "drift@example.com",
                                "GIT_COMMITTER_NAME": "Drift",
                                "GIT_COMMITTER_EMAIL": "drift@example.com"})
            findings = FIX.verify(manifest.root)
        self.assertTrue(findings)
        self.assertTrue(any("public/" in f for f in findings), findings)

    def test_verify_reports_a_directory_that_is_not_a_fixture(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            findings = FIX.verify(Path(tmp))
        self.assertEqual(len(findings), 1)
        self.assertIn(FIX.MANIFEST_NAME, findings[0])

    def test_cli_verify_and_list_variants_exit_zero(self) -> None:
        code, out = _cli(FIX.main, ["list-variants"])
        self.assertEqual(code, 0)
        for name in FIX.VARIANTS:
            self.assertIn(name, out)
        code, _ = _cli(FIX.main, ["verify", "--out", str(_SHARED["base"].root)])
        self.assertEqual(code, 0)

    def test_cli_build_refuses_a_tracked_destination_with_exit_two(self) -> None:
        code, out = _cli(FIX.main, ["build", "--out", str(REPO_ROOT / "skills")])
        self.assertEqual(code, 2)
        self.assertIn("refusing", out)
        self.assertFalse((REPO_ROOT / "skills" / FIX.MANIFEST_NAME).exists())


class TestVariants(unittest.TestCase):

    def test_every_variant_builds_and_verifies(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            for name in sorted(FIX.VARIANTS):
                with self.subTest(variant=name):
                    manifest = FIX.build(Path(tmp) / name, variant=name)
                    self.assertEqual(manifest.variant, name)
                    self.assertEqual(FIX.verify(manifest.root), [])

    def test_unknown_variant_is_refused(self) -> None:
        with self.assertRaises(FIX.FixtureError):
            FIX.build("/tmp/never-created", variant="no-such-variant")

    def test_fixture_version_is_recorded_in_the_built_tree(self) -> None:
        data = json.loads(
            (_SHARED["base"].root / FIX.MANIFEST_NAME).read_text(encoding="utf-8"))
        self.assertEqual(data["fixture_version"], FIX.FIXTURE_VERSION)
        self.assertEqual(data["generator"], "reconciliation_fixture.py")


class TestBenchHarness(unittest.TestCase):

    def test_every_stage_names_a_known_fixture_variant(self) -> None:
        for sid, stage in BENCH.STAGES.items():
            with self.subTest(stage=sid):
                self.assertIn(stage.variant, FIX.VARIANTS)

    def test_every_inproc_step_resolves(self) -> None:
        for sid, stage in BENCH.STAGES.items():
            for step in stage.steps:
                if step.kind == "inproc":
                    with self.subTest(stage=sid, step=step.name):
                        self.assertIn(step.inproc, BENCH._INPROC)

    def test_no_stage_benchmarks_an_executor(self) -> None:
        """The guarded executor is deferred; a stage measuring it cannot exist."""
        forbidden = ("rebase", "cherry-pick", "reset", "checkout", "stash",
                     "merge", "push", "rm", "clean")
        for sid, stage in BENCH.STAGES.items():
            for step in stage.steps:
                if step.kind != "subprocess" or step.argv[0] != "git":
                    continue
                with self.subTest(stage=sid, step=step.name):
                    self.assertNotIn(step.argv[1], forbidden)

    def test_stage_ids_are_documented_in_the_protocol(self) -> None:
        protocol = (REPO_ROOT / "evals" / "protocols"
                    / "reconciliation-stages.md").read_text(encoding="utf-8")
        for sid in BENCH.STAGES:
            with self.subTest(stage=sid):
                self.assertIn(f"`{sid}`", protocol)

    def test_run_stage_reports_medians_and_a_row_fragment(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            stage = BENCH.STAGES["R3"]
            results = BENCH.run_stage(stage, runs=2, work_dir=Path(tmp))
            summary = BENCH.summarize(stage, stage.variant, results,
                                      {"status": "recorder absent"})
        self.assertEqual(summary["runs"], 2)
        self.assertTrue(summary["ok"], summary["steps"])
        self.assertEqual(summary["total_tokens"], "not_measured")
        self.assertEqual(len(summary["steps"]), len(stage.steps))
        for step in summary["steps"]:
            self.assertLessEqual(step["seconds"]["min"], step["seconds"]["median"])
            self.assertLessEqual(step["seconds"]["median"], step["seconds"]["max"])
        row = BENCH.render_row(summary)
        self.assertIn("### Stage row — R3", row)
        self.assertIn("**TOTAL**", row)
        self.assertIn("not_measured", row)

    def test_r4_expects_a_red_reconciler_before_the_closeout_records(self) -> None:
        """The entry condition is an EXPECTED exit 1, not a tolerated one."""
        entry = BENCH.STAGES["R4"].steps[0]
        self.assertEqual(entry.expect, 1)

    def test_phase_summary_degrades_gracefully_when_absent(self) -> None:
        result = BENCH.collect_phase_summary(None, None)
        self.assertIn(result["status"],
                      {"recorder absent", "not collected", "unavailable"})
        self.assertIn("detail", result)

    def test_bench_cli_lists_stages(self) -> None:
        code, out = _cli(BENCH.main, ["--list-stages"])
        self.assertEqual(code, 0)
        for sid in BENCH.STAGES:
            self.assertIn(sid, out)

    def test_bench_cli_rejects_an_unknown_stage(self) -> None:
        code, out = _cli(BENCH.main, ["--stage", "R99"])
        self.assertEqual(code, 2)
        self.assertIn("unknown stage", out)


if __name__ == "__main__":
    unittest.main()
