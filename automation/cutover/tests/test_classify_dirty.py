"""Tests for the dirty-path classifier and its link-rebase residual normalizer.

Run with (from the repo root):
    .venv/bin/python -m unittest discover automation/cutover/tests

Two properties carry the weight here, and they pull in opposite directions on
purpose:

  * a path is only ever called ``renamed-by-merged-layout`` on PROOF — an
    exact-blob (``R100``) rename plus an identical merged blob.  A similarity
    rename is recorded and never classifies, because a heuristic rename that
    turns out wrong silently relocates a local edit into the wrong file;
  * the residual normalizer must be able to say "this upstream delta was
    path-only" for the generated-calendar case, and must REFUSE to say it the
    moment one semantic line also changed — even when every path in the file was
    rewritten.  Test 7 pins that failure direction.

Every test builds a throwaway Git repository under ``tempfile.mkdtemp`` with
deterministic identity/date environment, so nothing here reads the developer's
config, the private overlay, or the real repository.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

# Make the sibling module importable (automation/cutover/).
_CUTOVER_DIR = Path(__file__).resolve().parents[1]
if str(_CUTOVER_DIR) not in sys.path:
    sys.path.insert(0, str(_CUTOVER_DIR))

import classify_dirty as CD  # noqa: E402


GIT_ENV = {
    "GIT_AUTHOR_NAME": "Cutover Test",
    "GIT_AUTHOR_EMAIL": "cutover@example.invalid",
    "GIT_COMMITTER_NAME": "Cutover Test",
    "GIT_COMMITTER_EMAIL": "cutover@example.invalid",
    "GIT_AUTHOR_DATE": "2026-01-01T00:00:00+0000",
    "GIT_COMMITTER_DATE": "2026-01-01T00:00:00+0000",
    "GIT_CONFIG_NOSYSTEM": "1",
}


class GitFixture(unittest.TestCase):
    """A throwaway repository with an old layout, a merged layout, and a patch."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="cutover-classify-")).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        # HOME is redirected so a developer's ~/.gitconfig cannot change what the
        # fixture commits (hooks, templates, autocrlf, default branch).
        self.home = self.tmp / "home"
        self.home.mkdir()
        self.env = {**os.environ, **GIT_ENV, "HOME": str(self.home)}
        self.repo = self.tmp / "repo"
        self.repo.mkdir()
        self.git("init", "-q", ".")
        self.git("symbolic-ref", "HEAD", "refs/heads/main")

    # -- helpers ------------------------------------------------------------
    def git(self, *args: str, cwd: Path | None = None) -> str:
        completed = subprocess.run(
            ["git", *args], cwd=str(cwd or self.repo), env=self.env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)
        self.assertEqual(
            completed.returncode, 0,
            f"git {' '.join(args)} exited {completed.returncode}: "
            f"{completed.stdout.decode('utf-8', 'replace')}")
        return completed.stdout.decode("utf-8", "replace")

    def write(self, relative: str, text: str) -> None:
        target = self.repo / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")

    def commit(self, message: str) -> str:
        self.git("add", "-A")
        self.git("commit", "-qm", message)
        return self.git("rev-parse", "HEAD").strip()

    def status_entries(self) -> tuple[CD.StatusEntry, ...]:
        # ``--ignored=traditional`` with ``-uall`` is the ONLY combination that
        # lists individual files inside an ignored directory; ``matching`` reports
        # the directory, which is not a thing anyone can copy.
        completed = subprocess.run(
            ["git", "status", "--porcelain=v2", "--branch", "--untracked-files=all",
             "--ignored=traditional", "-z"],
            cwd=str(self.repo), env=self.env, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, check=False)
        self.assertEqual(completed.returncode, 0, completed.stderr.decode())
        return CD.parse_status_v2(completed.stdout)[1]

    def classify(self, base: str, merge_base: str) -> dict[str, CD.DirtyPath]:
        git = CD.ReadOnlyGit(self.repo)
        exact = git.run("diff", "--name-status", "-z", "-M100%", "--diff-filter=R",
                        merge_base, base, "--")
        loose = git.run("diff", "--name-status", "-z", "-M", "--diff-filter=R",
                        merge_base, base, "--")
        renames = CD.exact_rename_map(CD.renames_from_diff(exact.stdout))
        similarity = {r.old: r for r in CD.renames_from_diff(loose.stdout)
                      if not r.exact}
        pairs = CD.derive_prefix_pairs(renames)
        classified = CD.classify_entries(
            self.status_entries(), git=git, base=base, merge_base=merge_base,
            renames=renames, prefix_pairs=pairs, similarity=similarity)
        return {d.path: d for d in classified}


class LayoutFixture(GitFixture):
    """The shape this tool exists for: a merged layout move + a local patch.

    ``self.fork`` is the fork point (M), ``self.base`` is the merged layout (B).

    The layout commit moves three files byte-for-byte (``R100``) and moves a
    fourth — the generated calendar — while ALSO rewriting the relative links
    inside it.  That fourth file is the whole point: it is absent from the R100
    map by construction, so its destination has to come from the prefix pairs the
    R100 moves imply, and the residual check has to prove the delta was
    path-only.
    """

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

    def setUp(self) -> None:
        super().setUp()
        self.write(".gitignore", "scratch/\nresearch/\n")
        self.write("interviews/calendar.md", self.CALENDAR_OLD)
        self.write("interviews/log.md", "interview log\n")
        self.write("interviews/asset.md", "placeholder\n")
        self.write("companies/acme/notes.md", "acme notes\n")
        self.write("companies/acme/history.md", "acme history\n")
        self.fork = self.commit("old layout")

        self.git("checkout", "-qb", "layout")
        # ``git mv`` will not create the destination directory itself.
        (self.repo / "me/interviews/companies/acme").mkdir(parents=True)
        self.git("mv", "companies/acme/notes.md",
                 "me/interviews/companies/acme/notes.md")
        self.git("mv", "companies/acme/history.md",
                 "me/interviews/companies/acme/history.md")
        self.git("mv", "interviews/log.md", "me/interviews/log.md")
        self.git("mv", "interviews/calendar.md", "me/interviews/calendar.md")
        self.write("me/interviews/calendar.md", self.CALENDAR_MERGED)
        self.base = self.commit("person-first layout")

        self.git("checkout", "-q", "main")
        self.git("checkout", "-qb", "work")


# ── 1-5, 9: verdicts ─────────────────────────────────────────────────────────
class VerdictTests(LayoutFixture):

    def test_exact_rename_with_unchanged_blob_is_renamed_by_merged_layout(self) -> None:
        self.write("companies/acme/notes.md", "acme notes\nlocal addition\n")
        found = self.classify(self.base, self.fork)["companies/acme/notes.md"]
        self.assertEqual(found.verdict, CD.VERDICT_RENAMED)
        self.assertEqual(found.action, CD.ACTION_REPLAY)
        self.assertEqual(found.merged_path,
                         "me/interviews/companies/acme/notes.md")
        self.assertEqual(found.rename,
                         {"evidence": "R100", "exact": True, "score": 100})

    def test_an_upstream_move_and_edit_is_content_divergent(self) -> None:
        # An R100 pair proves the bytes did not change, so a content-divergent
        # path can never come from the R100 map.  Its destination comes from the
        # prefix pairs those R100 moves imply.
        self.write("interviews/calendar.md", self.CALENDAR_OLD + "- local todo\n")
        found = self.classify(self.base, self.fork)["interviews/calendar.md"]
        self.assertEqual(found.verdict, CD.VERDICT_CONTENT_DIVERGENT)
        self.assertEqual(found.action, CD.ACTION_AGENT_RESOLVE)
        self.assertEqual(found.merged_path, "me/interviews/calendar.md")
        self.assertEqual((found.rename or {}).get("evidence"), "prefix-pair")
        self.assertFalse((found.rename or {}).get("exact"))

    def test_the_calendar_case_proves_a_path_only_upstream_delta(self) -> None:
        # End to end, through real Git plumbing: the residual after link-rebase is
        # EMPTY, and the verdict STILL says agent work.  A proof is an input to
        # the agent's judgement, never a substitute for it.
        self.write("interviews/calendar.md", self.CALENDAR_OLD + "- local todo\n")
        found = self.classify(self.base, self.fork)["interviews/calendar.md"]
        self.assertEqual(found.residual_after_link_rebase, CD.RESIDUAL_EMPTY)
        self.assertEqual(found.residual_lines, 0)
        self.assertEqual(found.verdict, CD.VERDICT_CONTENT_DIVERGENT)
        self.assertEqual(found.action, CD.ACTION_AGENT_RESOLVE)

    def test_a_semantic_upstream_edit_leaves_a_non_empty_residual(self) -> None:
        self.git("checkout", "-q", "layout")
        self.write("me/interviews/calendar.md",
                   self.CALENDAR_MERGED.replace("# Calendar\n", "# Calendar 2026\n"))
        base = self.commit("upstream also changed a semantic line")
        self.git("checkout", "-q", "work")
        self.write("interviews/calendar.md", self.CALENDAR_OLD + "- local todo\n")
        found = self.classify(base, self.fork)["interviews/calendar.md"]
        self.assertEqual(found.verdict, CD.VERDICT_CONTENT_DIVERGENT)
        self.assertEqual(found.residual_after_link_rebase, CD.RESIDUAL_NON_EMPTY)
        self.assertEqual(found.residual_lines, 2)

    def test_a_binary_divergence_is_not_attempted(self) -> None:
        self.git("checkout", "-q", "layout")
        (self.repo / "me/interviews/asset.md").write_bytes(b"\x00\x01binary\n")
        (self.repo / "interviews/asset.md").unlink()
        base = self.commit("upstream moved the asset and made it binary")
        self.git("checkout", "-q", "work")
        (self.repo / "interviews/asset.md").write_bytes(b"placeholder + local\n")
        found = self.classify(base, self.fork)["interviews/asset.md"]
        self.assertEqual(found.verdict, CD.VERDICT_CONTENT_DIVERGENT)
        self.assertEqual(found.residual_after_link_rebase, CD.RESIDUAL_BINARY)
        self.assertEqual(found.action, CD.ACTION_AGENT_RESOLVE)

    def test_no_rename_evidence_and_absent_from_base_is_unknown(self) -> None:
        self.write("probe.json", "{}\n")
        found = self.classify(self.base, self.fork)["probe.json"]
        self.assertEqual(found.verdict, CD.VERDICT_UNKNOWN)
        self.assertEqual(found.action, CD.ACTION_OWNER)
        self.assertEqual([code for code, _ in found.blocking],
                         [CD.CODE_UNKNOWN_DIRTY])

    def test_worktree_blob_equal_to_fork_blob_is_unchanged(self) -> None:
        # Dirty by mtime + a staged-then-reverted edit: Git reports the path, the
        # bytes are the fork point's bytes, and nothing has to replay.
        self.write("companies/acme/history.md", "changed\n")
        self.git("add", "companies/acme/history.md")
        self.write("companies/acme/history.md", "acme history\n")
        found = self.classify(self.base, self.fork)["companies/acme/history.md"]
        self.assertEqual(found.verdict, CD.VERDICT_UNCHANGED)
        self.assertEqual(found.action, CD.ACTION_NONE)

    def test_ignored_file_is_never_given_action_replay(self) -> None:
        self.write("companies/acme/research/dossier.md", "dossier\n")
        found = self.classify(self.base, self.fork)["companies/acme/research/dossier.md"]
        self.assertEqual(found.verdict, CD.VERDICT_IGNORED)
        self.assertTrue(found.ignored)
        self.assertNotEqual(found.action, CD.ACTION_REPLAY)
        self.assertEqual(found.action, CD.ACTION_COPY)
        self.assertEqual(found.merged_path,
                         "me/interviews/companies/acme/research/dossier.md")

    def test_ignored_destination_with_different_bytes_blocks(self) -> None:
        self.write("companies/acme/research/dossier.md", "dossier\n")
        self.write("me/interviews/companies/acme/research/dossier.md", "OTHER\n")
        found = self.classify(self.base, self.fork)["companies/acme/research/dossier.md"]
        self.assertEqual(found.action, CD.ACTION_OWNER)
        self.assertFalse(found.destination_bytes_equal)
        self.assertEqual([code for code, _ in found.blocking],
                         [CD.CODE_IGNORED_CONFLICT])

    def test_ignored_destination_with_identical_bytes_is_already_copied(self) -> None:
        self.write("companies/acme/research/dossier.md", "dossier\n")
        self.write("me/interviews/companies/acme/research/dossier.md", "dossier\n")
        found = self.classify(self.base, self.fork)["companies/acme/research/dossier.md"]
        self.assertEqual(found.action, CD.ACTION_NONE)
        self.assertTrue(found.destination_bytes_equal)
        self.assertEqual(found.blocking, ())

    def test_ignored_file_with_no_layout_counterpart_is_reported_not_deleted(self) -> None:
        self.write("scratch/probe.json", "{}\n")
        found = self.classify(self.base, self.fork)["scratch/probe.json"]
        self.assertEqual(found.verdict, CD.VERDICT_IGNORED)
        self.assertIsNone(found.merged_path)
        # Reported, never assumed disposable: the owner decides, and no step
        # anywhere proposes removing it.
        self.assertEqual(found.action, CD.ACTION_OWNER)
        self.assertEqual(found.blocking, ())

    def test_similarity_rename_never_yields_renamed_by_merged_layout(self) -> None:
        body = "".join(f"line {i}\n" for i in range(20))
        self.write("legacy/report.md", body)
        self.commit("add a report")
        fork = self.git("rev-parse", "HEAD").strip()

        self.git("checkout", "-qb", "layout2")
        self.write("moved/report.md", body.replace("line 3\n", "line three CHANGED\n"))
        (self.repo / "legacy/report.md").unlink()
        base = self.commit("move and edit the report")
        self.git("checkout", "-q", "work")

        git = CD.ReadOnlyGit(self.repo)
        loose = CD.renames_from_diff(git.run(
            "diff", "--name-status", "-z", "-M", "--diff-filter=R", fork, base,
            "--").stdout)
        self.assertTrue(loose, "the fixture must produce a similarity rename")
        self.assertTrue(all(not r.exact for r in loose))
        self.assertEqual(CD.exact_rename_map(loose), {})

        self.write("legacy/report.md", body + "local edit\n")
        found = self.classify(base, fork)["legacy/report.md"]
        # A score may point at a destination for the AGENT to look at; it may
        # never claim the contents were preserved.
        self.assertNotEqual(found.verdict, CD.VERDICT_RENAMED)
        self.assertEqual(found.verdict, CD.VERDICT_CONTENT_DIVERGENT)
        self.assertEqual((found.rename or {}).get("evidence"), "similarity")
        self.assertFalse((found.rename or {}).get("exact"))
        self.assertEqual(found.action, CD.ACTION_AGENT_RESOLVE)

    def test_without_any_rename_evidence_a_moved_file_is_unknown(self) -> None:
        # Same shape as above, but the classifier is given no similarity map: the
        # honest answer is "no evidence", which REFUSES rather than guesses.
        body = "".join(f"line {i}\n" for i in range(20))
        self.write("legacy/report.md", body)
        self.commit("add a report")
        fork = self.git("rev-parse", "HEAD").strip()
        self.git("checkout", "-qb", "layout3")
        self.write("moved/report.md", body.replace("line 3\n", "line three CHANGED\n"))
        (self.repo / "legacy/report.md").unlink()
        base = self.commit("move and edit the report")
        self.git("checkout", "-q", "work")
        self.write("legacy/report.md", body + "local edit\n")

        git = CD.ReadOnlyGit(self.repo)
        classified = CD.classify_entries(
            self.status_entries(), git=git, base=base, merge_base=fork,
            renames={}, prefix_pairs=())
        found = {d.path: d for d in classified}["legacy/report.md"]
        self.assertEqual(found.verdict, CD.VERDICT_UNKNOWN)


# ── 6-8: the link-rebase residual normalizer ─────────────────────────────────
class NormalizerTests(unittest.TestCase):

    # Exactly what the layout fixture's R100 diff produces: the calendar is NOT
    # in it (its bytes changed), which is why its own destination has to come
    # from the prefix pairs these entries imply.
    RENAMES = {
        "interviews/log.md": "me/interviews/log.md",
        "companies/acme/notes.md": "me/interviews/companies/acme/notes.md",
    }

    def setUp(self) -> None:
        self.pairs = CD.derive_prefix_pairs(self.RENAMES)

    def normalize(self, text: str) -> str:
        return CD.link_rebase(
            text, path="interviews/calendar.md",
            merged_path="me/interviews/calendar.md",
            renames=self.RENAMES, prefix_pairs=self.pairs)

    def test_prefix_pairs_are_derived_from_the_exact_rename_map(self) -> None:
        self.assertEqual(
            set(self.pairs),
            {("interviews", "me/interviews"),
             ("companies", "me/interviews/companies")})

    def test_a_partially_moved_directory_yields_no_prefix_pair(self) -> None:
        renames = {
            "companies/acme/notes.md": "me/interviews/companies/acme/notes.md",
            "companies/beta/notes.md": "market/companies/beta/notes.md",
        }
        self.assertEqual(CD.derive_prefix_pairs(renames), ())

    def test_residual_is_empty_for_a_path_only_upstream_delta(self) -> None:
        normalized = self.normalize(LayoutFixture.CALENDAR_OLD)
        self.assertEqual(normalized, LayoutFixture.CALENDAR_MERGED)
        self.assertEqual(
            CD.residual_line_count(normalized, LayoutFixture.CALENDAR_MERGED), 0)

    def test_residual_is_non_empty_when_one_semantic_line_also_changed(self) -> None:
        merged = LayoutFixture.CALENDAR_MERGED.replace(
            "# Calendar\n", "# Calendar (2026)\n")
        normalized = self.normalize(LayoutFixture.CALENDAR_OLD)
        self.assertNotEqual(normalized, merged)
        self.assertEqual(CD.residual_line_count(normalized, merged), 2)

    def test_a_target_that_does_not_resolve_into_the_map_is_left_alone(self) -> None:
        text = "see [other](../unrelated/file.md) and [abs](/etc/passwd)\n"
        self.assertEqual(self.normalize(text), text)

    def test_an_http_target_is_never_rewritten(self) -> None:
        text = "see [site](https://example.invalid/companies/acme/notes.md)\n"
        self.assertEqual(self.normalize(text), text)

    def test_a_prefix_match_needs_a_path_component_boundary(self) -> None:
        # ``companies-log/`` and an already-migrated ``me/companies/`` must not be
        # touched by the ``companies`` -> ``me/interviews/companies`` pair.
        text = "companies-log/x.md and me/companies/y.md\n"
        self.assertEqual(self.normalize(text), text)

    def test_a_link_rewrite_is_never_re_prefixed_by_a_directory_pair(self) -> None:
        # The output of the link pass ("companies/acme/notes.md", relative to the
        # file's NEW directory) would be re-prefixed if the two families were
        # applied sequentially instead of as one non-overlapping pass.
        text = "[n](../companies/acme/notes.md)\n"
        self.assertEqual(self.normalize(text), "[n](companies/acme/notes.md)\n")


# ── 10 + parsing safety ──────────────────────────────────────────────────────
class ParsingSafetyTests(unittest.TestCase):

    def test_a_diff_path_with_a_line_break_raises(self) -> None:
        payload = b"R100\0old\nname.md\0new.md\0"
        with self.assertRaises(CD.ClassificationError):
            CD.renames_from_diff(payload)

    def test_a_status_path_with_a_line_break_raises(self) -> None:
        payload = b"1 .M N... 100644 100644 100644 aaaa bbbb we\nird.md\0"
        with self.assertRaises(CD.ClassificationError):
            CD.parse_status_v2(payload)

    def test_a_non_utf8_status_path_raises(self) -> None:
        payload = b"1 .M N... 100644 100644 100644 aaaa bbbb \xff\xfe.md\0"
        with self.assertRaises(CD.ClassificationError):
            CD.parse_status_v2(payload)

    def test_a_rename_record_carries_its_origin_as_the_next_nul_field(self) -> None:
        payload = (b"# branch.head work\0"
                   b"2 R. N... 100644 100644 100644 aaaa bbbb R100 new name.md\0"
                   b"old name.md\0")
        branch, entries = CD.parse_status_v2(payload)
        self.assertEqual(branch.head, "work")
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].path, "new name.md")
        self.assertEqual(entries[0].orig_path, "old name.md")

    def test_branch_ab_is_parsed_as_ahead_and_behind(self) -> None:
        branch, _ = CD.parse_status_v2(b"# branch.ab +3 -12\0")
        self.assertEqual((branch.ahead, branch.behind), (3, 12))

    def test_an_unsupported_record_kind_raises(self) -> None:
        with self.assertRaises(CD.ClassificationError):
            CD.parse_status_v2(b"z something\0")

    def test_the_nul_walker_is_imported_not_reimplemented(self) -> None:
        import classify_changes  # noqa: PLC0415 - proving the identity is the point
        self.assertIs(CD.parse_name_status, classify_changes.parse_name_status)
        self.assertIs(CD.ClassificationError, classify_changes.ClassificationError)


# ── the read-only promise, enforced structurally ─────────────────────────────
class ReadOnlyGitTests(GitFixture):

    def setUp(self) -> None:
        super().setUp()
        self.write("a.md", "a\n")
        self.commit("first")
        self.git_api = CD.ReadOnlyGit(self.repo)

    def test_hash_object_dash_w_is_refused(self) -> None:
        with self.assertRaises(CD.GitError):
            self.git_api.run("hash-object", "-w", "--", "a.md")

    def test_hash_object_without_w_writes_no_object(self) -> None:
        before = sorted(p.name for p in (self.repo / ".git/objects").rglob("*"))
        (self.repo / "b.md").write_text("brand new content\n")
        oid = self.git_api.hash_object("b.md")
        self.assertRegex(oid or "", r"^[0-9a-f]{40}$")
        after = sorted(p.name for p in (self.repo / ".git/objects").rglob("*"))
        self.assertEqual(before, after)

    def test_a_mutating_subcommand_is_refused(self) -> None:
        for args in (("commit", "-m", "x"), ("add", "-A"), ("push",), ("rebase",),
                     ("checkout", "--", "a.md"), ("clean", "-fd"), ("reset", "--hard"),
                     ("update-ref", "refs/x", "HEAD"), ("rm", "a.md"),
                     ("worktree", "remove", "x"), ("remote", "add", "o", "u")):
            with self.subTest(args=args):
                with self.assertRaises(CD.GitError):
                    self.git_api.run(*args)

    def test_fetch_needs_explicit_authorisation(self) -> None:
        with self.assertRaises(CD.GitError):
            self.git_api.run("fetch", "--prune", "origin")
        authorised = CD.ReadOnlyGit(self.repo, allow_fetch=True)
        # No remote here, so it exits nonzero — the point is that the guard
        # allowed the invocation rather than raising.
        self.assertNotEqual(
            authorised.run("fetch", "--prune", "origin", check=False).returncode, 0)

    def test_a_dirty_gitlink_is_unsafe_and_blocks(self) -> None:
        # Git will not let a fixture produce a dirty submodule without a second
        # repository and a submodule registration, so the porcelain=v2 record is
        # supplied directly: the ``S`` in the fourth field IS the whole signal.
        entry = CD.StatusEntry("1", ".M", "SCM.", "vendor/thing")
        found = CD.classify_entry(
            entry, git=self.git_api, base="HEAD", merge_base="HEAD",
            renames={}, prefix_pairs=(), ignored_paths=())
        self.assertEqual(found.verdict, CD.VERDICT_UNSAFE)
        self.assertEqual(found.action, CD.ACTION_OWNER)
        self.assertEqual([code for code, _ in found.blocking],
                         [CD.CODE_SUBMODULE_DIRTY])

    def test_a_clean_submodule_field_is_not_treated_as_a_gitlink(self) -> None:
        entry = CD.StatusEntry("1", ".M", "N...", "a.md")
        found = CD.classify_entry(
            entry, git=self.git_api, base="HEAD", merge_base="HEAD",
            renames={}, prefix_pairs=(), ignored_paths=())
        self.assertNotEqual(found.verdict, CD.VERDICT_UNSAFE)

    def test_check_ignore_batches_and_never_reports_a_tracked_path(self) -> None:
        self.write(".gitignore", "ignored/\n")
        self.commit("ignore rules")
        self.write("ignored/x.md", "x\n")
        self.assertEqual(self.git_api.ignored(["ignored/x.md", "a.md"]),
                         {"ignored/x.md"})


# ── naming discipline (decision 1) ───────────────────────────────────────────
class NamingTests(unittest.TestCase):
    """Decision 1: nothing reachable by the word "reconcile" may live here.

    ``automation/reconcile/reconcile.py`` is the process-layer schema referee
    wired into pre-commit and CI.  An agent told to "run the reconciler" must not
    be able to reach a git-state planner by that word, so no FILE and no
    IDENTIFIER in this folder may carry it.  Prose that explicitly disambiguates
    the two is the point and is allowed.
    """

    def test_no_file_here_is_named_reconcile(self) -> None:
        for path in sorted(_CUTOVER_DIR.rglob("*.py")):
            self.assertNotIn("reconcile", path.name.lower(), str(path))

    def test_no_identifier_here_is_named_reconcile(self) -> None:
        import ast  # noqa: PLC0415 - local to the one test that needs it

        for path in sorted(_CUTOVER_DIR.glob("*.py")):
            tree = ast.parse(path.read_text(), filename=str(path))
            for node in ast.walk(tree):
                names: list[str] = []
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                                     ast.ClassDef)):
                    names.append(node.name)
                elif isinstance(node, ast.Name):
                    names.append(node.id)
                elif isinstance(node, ast.arg):
                    names.append(node.arg)
                elif isinstance(node, ast.Attribute):
                    names.append(node.attr)
                for name in names:
                    self.assertNotIn("reconcile", name.lower(),
                                     f"{path.name}: identifier {name!r}")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
