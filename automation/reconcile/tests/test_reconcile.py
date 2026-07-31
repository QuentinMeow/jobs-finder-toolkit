"""Tests for the reconciler's root handling and retry filing.

Run with (from the repo root):
    .venv/bin/python -m unittest discover \
        -s automation/reconcile/tests -t automation/reconcile/tests

Two behaviours are pinned here, and they pull in opposite directions on purpose:

  * the missing-root NO-OP is DOCUMENTED, not a defect — the published tree ships
    none of message-queue/, tasks/, memory/, docs/roadmap/, history/, so plain
    ``--check`` must stay green without them. ``--require-roots`` is the opt-in
    maintainer assertion that fails on exactly the same tree;
  * ``file_retries()`` must not create ``message-queue/needs-agent/retries/``
    when there is nothing to file — a repo that deleted that queue used to get it
    silently re-created on every clean run.

``company-index`` is the one check that reads the private overlay, and three tests
here pin the three things that keep that exception from reaching a public tree: it
no-ops without ``private/companies/``, ``--require-roots`` never asserts a private
root, and ``file_retries`` never writes a private subject into the TRACKED retry
queue (a retry item's filename and body carry the finding's subject verbatim, so
filing one would commit an application slug or a company key).

Every test runs against a throwaway tree, never the real repo and never the real
overlay.
"""
from __future__ import annotations

import datetime
import inspect
import shutil
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

RECONCILE_DIR = Path(__file__).resolve().parents[1]
if str(RECONCILE_DIR) not in sys.path:
    sys.path.insert(0, str(RECONCILE_DIR))

import reconcile as R  # noqa: E402


class TempRepo(unittest.TestCase):
    """A temp tree standing in for REPO_ROOT."""

    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="reconcile-")).resolve()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self._saved = (R.REPO_ROOT, R.RETRIES_DIR)
        R.REPO_ROOT = self.root
        R.RETRIES_DIR = self.root / "message-queue/needs-agent/retries"
        self.addCleanup(self._restore)

    def _restore(self) -> None:
        R.REPO_ROOT, R.RETRIES_DIR = self._saved

    def make_roots(self, *, skip: tuple[str, ...] = ()) -> None:
        """Create every PUBLIC check root in the temp tree.

        Private roots are never created here: they are never asserted, and
        materialising ``private/companies/`` would make ``check_company_index``
        run against a bare temp tree that has no ``automation/shared`` to import.
        The company-index tests below drive that check directly instead.
        """
        for root in sorted(set(R.CHECK_ROOTS.values())):
            if root in skip or root.startswith("private/"):
                continue
            (self.root / root).mkdir(parents=True, exist_ok=True)


class TestRequireRoots(TempRepo):

    def test_all_roots_present_is_clean(self) -> None:
        self.make_roots()
        self.assertEqual(R.check_required_roots(), [])

    def test_missing_root_is_a_finding(self) -> None:
        self.make_roots(skip=("tasks",))
        findings = R.check_required_roots()
        self.assertEqual([f.subject for f in findings], ["tasks"])
        self.assertIn("task-structure", findings[0].message)

    def test_every_root_is_asserted(self) -> None:
        # No roots at all: one finding per distinct guarded PUBLIC root, deduped.
        self.assertEqual(
            [f.subject for f in R.check_required_roots()],
            sorted({r for r in R.CHECK_ROOTS.values() if not r.startswith("private/")}),
        )

    def test_private_roots_are_not_required(self) -> None:
        """--require-roots must never assert a private root.

        ``automation/hooks/pre-commit`` runs ``--require-roots`` whenever ``private/``
        is merely mounted, so asserting one would make the shape of an overlay — a
        separate repository with its own lifecycle — a gate on every public commit.
        """
        private_roots = {r for r in R.CHECK_ROOTS.values() if r.startswith("private/")}
        self.assertTrue(private_roots, "precondition: at least one private root exists")
        subjects = {f.subject for f in R.check_required_roots()}
        self.assertEqual(subjects & private_roots, set())

    def test_the_pre_commit_hook_requires_roots_when_the_overlay_is_mounted(self) -> None:
        """The claim the skip above rests on, pinned against the real hook."""
        hook = (Path(__file__).resolve().parents[3]
                / "automation/hooks/pre-commit").read_text(encoding="utf-8")
        self.assertIn("if [ -d private ]", hook)
        self.assertIn("--check --require-roots", hook)

    def test_plain_check_still_passes_on_the_same_tree(self) -> None:
        """The published-export shape: skills/ but no process roots → --check green.

        ``skill-manifests`` is dropped for this run only: it imports
        ``sync_skill_manifests`` out of ``REPO_ROOT/automation/publish``, which a
        bare temp tree has no copy of. It is covered by automation/publish/tests.
        """
        self.make_roots(skip=("message-queue", "tasks", "memory",
                              "docs/roadmap", "history/conversations"))
        saved = R.CHECKS
        R.CHECKS = {k: v for k, v in saved.items() if k != "skill-manifests"}
        self.addCleanup(lambda: setattr(R, "CHECKS", saved))
        plain = R.main(["--check"])
        strict = R.main(["--check", "--require-roots"])
        self.assertEqual(plain, 0, "plain --check must tolerate absent process roots")
        self.assertEqual(strict, 1, "--require-roots must fail on the same tree")

    def test_check_roots_cover_every_check(self) -> None:
        """A new check without a declared root would silently escape the flag."""
        self.assertEqual(set(R.CHECK_ROOTS), set(R.CHECKS))


class TestRoadmapDated(TempRepo):
    """The gate reads the date, and stops there. MALFORMED fails; OLD does not.

    It used to test that the string ``Last-updated`` appeared anywhere in
    ``current-state.md``, so ``Last-updated: whenever`` passed. Then it briefly aged
    the date too — in a check that runs in pre-commit AND CI, which would have failed
    every commit in the repo a month after the last re-date. Age now lives in the
    gardener's report-only ``roadmap-staleness`` routine; this class pins BOTH halves
    of that split, because a gate that quietly resumed blocking on age is the exact
    regression the split exists to prevent.
    """

    TODAY = datetime.date(2026, 7, 31)

    def roadmap(self, current: str, *, desired: bool = True) -> None:
        (self.root / "docs/roadmap").mkdir(parents=True, exist_ok=True)
        (self.root / "docs/roadmap/current-state.md").write_text(
            current, encoding="utf-8")
        if desired:
            (self.root / "docs/roadmap/desired-state.md").write_text(
                "# Desired state\n", encoding="utf-8")

    def messages(self) -> list[str]:
        return [f.message for f in R.check_roadmap_dated(today=self.TODAY)]

    def test_a_recent_date_passes(self) -> None:
        self.roadmap("# Current state\n\n- **Last-updated**: 2026-07-30\n")
        self.assertEqual(R.check_roadmap_dated(today=self.TODAY), [])

    def test_a_year_stale_roadmap_does_not_block_a_commit(self) -> None:
        """The whole point of the split: staleness is a reminder, not an outage."""
        self.roadmap("# Current state\n\n- **Last-updated**: 2025-07-30\n")
        self.assertEqual(R.check_roadmap_dated(today=self.TODAY), [])

    def test_no_finding_message_mentions_an_age_limit(self) -> None:
        """Guards against age quietly coming back through a message tweak."""
        for body in ("- **Last-updated**: 2020-01-01\n",
                     "- **Last-updated**: whenever\n",
                     "- **Last-updated**: 2027-01-01\n",
                     "# Current state\n\nno date here\n"):
            self.roadmap(body)
            for message in self.messages():
                self.assertNotIn("days old", message, body)
                self.assertNotIn("limit", message, body)

    def test_an_unparseable_date_is_a_finding(self) -> None:
        self.roadmap("- **Last-updated**: whenever\n")
        self.assertIn("is not an ISO date", self.messages()[0])

    def test_a_future_date_is_a_finding(self) -> None:
        """Otherwise an age check is defeated by typing a date nobody can age past."""
        self.roadmap("- **Last-updated**: 2027-01-01\n")
        self.assertIn("in the future", self.messages()[0])

    def test_a_missing_line_still_reads_as_undated(self) -> None:
        self.roadmap("# Current state\n\nno date here\n")
        self.assertIn("missing a Last-updated line", self.messages()[0])

    def test_a_missing_desired_state_is_a_finding(self) -> None:
        """Named in the check's contract since it was written, never checked."""
        self.roadmap("- **Last-updated**: 2026-07-30\n", desired=False)
        subjects = [f.subject for f in R.check_roadmap_dated(today=self.TODAY)]
        self.assertEqual(subjects, ["docs/roadmap/desired-state.md"])

    def test_an_absent_roadmap_root_still_no_ops(self) -> None:
        """The published export ships no docs/roadmap/; plain --check stays green."""
        self.assertFalse((self.root / "docs/roadmap").exists())
        self.assertEqual(R.check_roadmap_dated(today=self.TODAY), [])

    def test_the_real_roadmap_is_well_formed_today(self) -> None:
        """Blast radius: this repo's own roadmap must pass the check."""
        saved = R.REPO_ROOT
        R.REPO_ROOT = Path(__file__).resolve().parents[3]
        self.addCleanup(lambda: setattr(R, "REPO_ROOT", saved))
        self.assertEqual(R.check_roadmap_dated(), [])

    def test_the_parser_is_the_one_the_gardener_imports(self) -> None:
        """Both readers must agree on what the date IS before they differ on age."""
        self.assertEqual(R.parse_last_updated("- **Last-updated**: `2026-07-30`\n"),
                         ("2026-07-30", datetime.date(2026, 7, 30)))
        self.assertEqual(R.parse_last_updated("nothing here\n"), (None, None))
        raw, stamp = R.parse_last_updated("- **Last-updated**: whenever\n")
        self.assertEqual((raw, stamp), ("whenever", None))


class TestFileRetries(TempRepo):

    def test_zero_findings_does_not_create_the_queue(self) -> None:
        R.file_retries([], "2026-07-29")
        self.assertFalse(R.RETRIES_DIR.exists())
        self.assertFalse((self.root / "message-queue").exists())

    def test_zero_findings_still_gcs_an_existing_queue(self) -> None:
        R.RETRIES_DIR.mkdir(parents=True)
        stale = R.RETRIES_DIR / "queue-schema--gone.md"
        stale.write_text(f"- **Filed**: 2026-01-01, {R.RECONCILER_SIGNATURE}\n",
                         encoding="utf-8")
        R.file_retries([], "2026-07-29")
        self.assertTrue(R.RETRIES_DIR.is_dir())
        self.assertFalse(stale.exists())

    def test_findings_create_the_queue_and_the_item(self) -> None:
        f = R.Finding("roadmap-dated", "docs/roadmap/current-state.md", "missing")
        R.file_retries([f], "2026-07-29")
        item = R.RETRIES_DIR / R._retry_name(f)
        self.assertTrue(item.is_file())
        self.assertIn("**Check**: roadmap-dated", item.read_text(encoding="utf-8"))

    def test_hand_written_items_survive_the_gc(self) -> None:
        R.RETRIES_DIR.mkdir(parents=True)
        mine = R.RETRIES_DIR / "human-filed.md"
        mine.write_text("- **Filed**: 2026-07-01, by a human\n", encoding="utf-8")
        R.file_retries([], "2026-07-29")
        self.assertTrue(mine.is_file())

    def test_private_findings_are_never_filed(self) -> None:
        """A retry item is TRACKED, so a private subject would be published.

        The item's filename is the slugified subject and its body repeats the
        subject and message verbatim; for ``company-index`` those are an
        application path and a company key.
        """
        self.assertIn("company-index", R.PRIVATE_CHECKS)
        private = R.Finding("company-index", "private/companies/_index.yaml", "boom")
        public = R.Finding("roadmap-dated", "docs/roadmap/current-state.md", "missing")
        R.file_retries([private, public], "2026-07-30")
        filed = sorted(p.name for p in R.RETRIES_DIR.iterdir())
        self.assertEqual(filed, [R._retry_name(public)])

    def test_a_previously_filed_private_item_is_collected(self) -> None:
        """The filter runs before the GC, so an item filed by an older build goes."""
        R.RETRIES_DIR.mkdir(parents=True)
        stale = R.RETRIES_DIR / "company-index--private-companies-index-yaml.md"
        stale.write_text(f"- **Filed**: 2026-07-01, {R.RECONCILER_SIGNATURE}\n",
                         encoding="utf-8")
        R.file_retries([R.Finding("company-index", "private/companies/_index.yaml",
                                  "boom")], "2026-07-30")
        self.assertFalse(stale.exists())


class TestCompanyIndexCheck(TempRepo):
    """The one check that reads the private overlay.

    ``company_index_findings`` is driven directly with explicit paths: the real
    ``check_company_index`` reads ``config.applications_root()``, which a throwaway
    tree has no config for.
    """

    INDEX = textwrap.dedent("""\
        acme-labs:
          display: Acme Labs
          aliases: [Acme Labs Inc.]
          kind: employer
        """)

    def index_at(self, text: str) -> Path:
        path = self.root / R.COMPANY_INDEX_ROOT / "_index.yaml"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def application(self, slug: str, body: str) -> Path:
        apps = self.root / "apps" / "6_drafted" / slug
        apps.mkdir(parents=True, exist_ok=True)
        (apps / "meta.yaml").write_text(body, encoding="utf-8")
        return self.root / "apps"

    # ── the no-op, which is what makes this check safe to ship publicly ──────

    def test_company_index_check_noops_without_the_root(self) -> None:
        self.assertFalse((self.root / R.COMPANY_INDEX_ROOT).exists())
        self.assertEqual(R.check_company_index(), [])

    def test_the_is_dir_guard_precedes_every_import(self) -> None:
        """reconcile.py is stdlib-only on a bare clone (module docstring).

        Asserted on the SOURCE rather than behaviourally: ``yaml`` is imported by
        the time any other test runs, so a behavioural assertion could not fail.
        """
        src = inspect.getsource(R.check_company_index)
        guard = src.index("if not root.is_dir():")
        for statement in ("_shared_import(", "import yaml"):
            if statement in src:
                self.assertLess(guard, src.index(statement),
                                f"{statement} must sit below the is_dir() guard")
        body = inspect.getsource(R.company_index_findings)
        self.assertLess(body.index("if not index_path.exists()"),
                        body.index("import yaml"))

    def test_an_absent_index_file_is_not_a_finding(self) -> None:
        """The root can exist before the owner has written the index.

        That is the state this PR lands into, and it is why the public half is
        safe to merge before the private half exists.
        """
        (self.root / R.COMPANY_INDEX_ROOT).mkdir(parents=True)
        self.assertEqual(R.check_company_index(), [])

    def test_the_root_constant_is_the_index_paths_parent(self) -> None:
        """One literal for the file, one for the folder; they must agree."""
        company_index = R._shared_import("company_index")
        self.assertEqual(Path(company_index.DEFAULT_REL).parent.as_posix(),
                         R.COMPANY_INDEX_ROOT)

    # ── family 1: index integrity ───────────────────────────────────────────

    def test_a_clean_index_reports_nothing(self) -> None:
        self.assertEqual(R.company_index_findings(self.index_at(self.INDEX), None), [])

    def test_integrity_findings_are_reported(self) -> None:
        path = self.index_at(self.INDEX + textwrap.dedent("""\
            acme-cloud:
              display: Acme Cloud
              aliases: [acme labs inc.]
              kind: employer
            """))
        findings = R.company_index_findings(path, None)
        self.assertEqual([f.check for f in findings], ["company-index"])
        self.assertIn("already claimed by", findings[0].message)
        self.assertIn("acme-cloud", findings[0].message)

    def test_malformed_yaml_is_a_finding_not_a_traceback(self) -> None:
        path = self.index_at("acme-labs: [unclosed\n")
        findings = R.company_index_findings(path, None)
        self.assertEqual(len(findings), 1)
        self.assertIn("unreadable", findings[0].message)

    # ── family 2: key resolution, meta.yaml -> index and never the reverse ───

    def test_company_key_not_in_index_is_a_finding(self) -> None:
        apps = self.application("acme-cloud-swe-20260730",
                                "company: Acme Cloud\ncompany_key: acme-cloud\n")
        findings = R.company_index_findings(self.index_at(self.INDEX), apps)
        self.assertEqual(len(findings), 1)
        self.assertIn("is not a key in", findings[0].message)
        self.assertTrue(findings[0].subject.endswith("meta.yaml"), findings[0].subject)

    def test_a_resolvable_company_key_is_clean(self) -> None:
        apps = self.application("acme-labs-swe-20260730",
                                "company: Acme Labs\ncompany_key: acme-labs\n")
        self.assertEqual(R.company_index_findings(self.index_at(self.INDEX), apps), [])

    def test_a_non_string_company_key_is_a_finding(self) -> None:
        apps = self.application("acme-labs-swe-20260730",
                                "company: Acme Labs\ncompany_key: 7\n")
        findings = R.company_index_findings(self.index_at(self.INDEX), apps)
        self.assertIn("must be a lowercase company-index key", findings[0].message)

    def test_every_malformed_company_key_is_a_finding_here_too(self) -> None:
        """The three validators must agree on the SAME five input classes.

        Each value below is an ERROR to ``job_metadata.validate_meta`` and a
        malformed row to ``status.py --company-keys``; before this, the trailing
        newline reached the MEMBERSHIP test here and was reported as a missing key,
        which told the owner to add a newline to their index.
        """
        index = self.index_at(self.INDEX)
        for name, literal in (("trailing-newline", '"acme-labs\\n"'),
                              ("empty-string", '""'),
                              ("false", "false"),
                              ("zero", "0")):
            with self.subTest(shape=name):
                slug = f"acme-labs-{name}-20260730"
                apps = self.application(slug,
                                        f"company: Acme Labs\ncompany_key: {literal}\n")
                mine = [f for f in R.company_index_findings(index, apps)
                        if slug in f.subject]
                self.assertEqual(len(mine), 1, mine)
                self.assertIn("must be a lowercase company-index key", mine[0].message)

    def test_a_directory_at_the_index_path_is_a_finding_not_a_no_op(self) -> None:
        """``is_file()`` is False for a directory, so the check used to go clean.

        A ``chmod 000`` file already reported ``unreadable``; a path that is not a
        regular file is the same "cannot read the index" state and must report the
        same way — silently returning clean while applications carry keys is the
        one answer that is wrong.
        """
        path = self.root / R.COMPANY_INDEX_ROOT / "_index.yaml"
        path.mkdir(parents=True)
        apps = self.application("acme-labs-swe-20260730",
                                "company: Acme Labs\ncompany_key: acme-labs\n")
        findings = R.company_index_findings(path, apps)
        self.assertEqual(len(findings), 1, findings)
        self.assertIn("unreadable", findings[0].message)
        self.assertIn("not a regular file", findings[0].message)

    def test_a_dangling_symlink_at_the_index_path_is_a_finding(self) -> None:
        path = self.root / R.COMPANY_INDEX_ROOT / "_index.yaml"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.symlink_to(self.root / "nowhere.yaml")
        findings = R.company_index_findings(path, None)
        self.assertEqual(len(findings), 1, findings)
        self.assertIn("unreadable", findings[0].message)

    def test_an_empty_index_file_is_a_finding(self) -> None:
        """0 keys is what a truncated file reports; it must not read as clean."""
        findings = R.company_index_findings(self.index_at(""), None)
        self.assertEqual(len(findings), 1, findings)
        self.assertIn("empty", findings[0].message)

    def test_a_duplicate_top_level_key_is_a_finding(self) -> None:
        """PyYAML keeps the LAST one, so one employer is deleted in silence."""
        path = self.index_at(self.INDEX + textwrap.dedent("""\
            acme-labs:
              display: Acme Cloud
              kind: employer
            """))
        findings = R.company_index_findings(path, None)
        self.assertTrue(any("defined more than once" in f.message for f in findings),
                        findings)

    def test_an_unkeyed_application_is_not_a_finding(self) -> None:
        """Coverage is a number status.py prints, never a gate.

        New applications are scaffolded without a key by design, so gating this
        would block unrelated public commits made between scaffolding and keying.

        BOTH shapes are covered on purpose. A file with no ``company_key`` text at
        all never reaches the branch — the cheap substring prefilter drops it first
        — so testing only that shape passes even when coverage IS gated. Mutation
        testing caught exactly that: gating coverage left this suite green until
        the second case was added.
        """
        index = self.index_at(self.INDEX)
        for name, body in (
            ("no-mention", "company: Acme Labs\n"),
            ("explicit-null", "company: Acme Labs\ncompany_key:\n"),
        ):
            with self.subTest(shape=name):
                apps = self.application(f"acme-labs-{name}-20260730", body)
                self.assertEqual(R.company_index_findings(index, apps), [])

    def test_a_key_with_no_applications_is_not_a_finding(self) -> None:
        """The direction is meta.yaml -> index, NEVER the reverse.

        A researched-but-never-applied employer is a legitimate key, and the
        reverse check would turn the reconciler red the moment the owner deletes an
        application folder — which AGENTS.md explicitly reserves to them.
        """
        apps = self.application("acme-labs-swe-20260730",
                                "company: Acme Labs\ncompany_key: acme-labs\n")
        path = self.index_at(self.INDEX + textwrap.dedent("""\
            acme-quiet:
              display: Acme Quiet Systems
              kind: employer
            """))
        self.assertEqual(R.company_index_findings(path, apps), [])

    def test_an_unparseable_meta_is_skipped_not_reported(self) -> None:
        """meta.yaml's own schema belongs to job_metadata, not to this check."""
        apps = self.application("acme-labs-swe-20260730", "company_key: [unclosed\n")
        self.assertEqual(R.company_index_findings(self.index_at(self.INDEX), apps), [])


if __name__ == "__main__":
    unittest.main()
