"""Tests for the verify-links gardener routine.

Run with (from the repo root):
    .venv/bin/python -m unittest discover \
        -s automation/gardener/tests \
        -t automation/gardener/tests

Every test builds a throwaway repo tree and points ``_common.REPO_ROOT`` at it, so
nothing here reads the real repo (or the private overlay).

The regressions pinned here, oldest first:
  * the routine used to read 23 files (AGENTS.md + ``skills/*/{SKILL,LESSONS,
    reference,AGENTS}.md``) out of ~155 tracked docs, so a stale path anywhere in
    ``docs/handbook/``, ``memory/``, ``README.md`` … was invisible;
  * ``check_symlinks()`` used to report "all resolve" when it found NO link root
    to walk — a fail-open that a restructure would trip silently;
  * markdown links (``[t](d)``, ``![a](d)``, ``[t][label]``, HTML ``href``/``src``)
    were never read at all, so every hyperlink in the tree was unverified;
  * a backticked token whose first segment matched no recognised root fell through
    with NO counter touched, so renaming a root migrated references into invisibility
    one at a time (``handbook/`` → ``docs/handbook/`` moved ~19 of them and nothing
    said so);
  * a broken reference's fate used to be one flat "advisory or not"; it is now three
    tiers keyed on what the SOURCE document is for, and an unknown ``tasks/`` status
    folder must fall through to the strict default rather than inherit advisory from a
    blanket ``tasks/`` prefix;
  * the overlay's ~1000 tracked ``.md`` were invisible because ``private/`` is a
    SEPARATE git repository and ``git ls-files`` in the public repo cannot see it.

``check_references()`` returns ``(broken, advisory, permitted, skipped,
unrecognised)``. Two tests are ``@unittest.expectedFailure``: they encode a case the
design's §7 test plan requires and the module does not yet implement, so they flip to
an UNEXPECTED SUCCESS the moment the module is fixed. Each says so in its docstring.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

GARDENER_DIR = Path(__file__).resolve().parents[1]
if str(GARDENER_DIR) not in sys.path:
    sys.path.insert(0, str(GARDENER_DIR))

import _common as C  # noqa: E402
import verify_links as V  # noqa: E402

BROKEN_REF = "skills/no-such-skill/SKILL.md"


def _legacy_instruction_files() -> list[Path]:
    """The pre-widening source set, kept verbatim to prove what it missed."""
    files = [C.REPO_ROOT / "AGENTS.md"]
    skills = C.REPO_ROOT / "skills"
    for name in ("SKILL.md", "LESSONS.md", "reference.md", "AGENTS.md"):
        files.extend(sorted(skills.glob(f"*/{name}")))
    return [f for f in files if f.is_file()]


class VerifyLinksTestCase(unittest.TestCase):
    """Base: a temp tree standing in for the repo root."""

    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="verify-links-")).resolve()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self._saved_root = C.REPO_ROOT
        C.REPO_ROOT = self.root
        self.addCleanup(lambda: setattr(C, "REPO_ROOT", self._saved_root))
        # ``--no-overlay`` is a MODULE-level global that ``main()`` writes and
        # nothing resets; a test that flips it would otherwise silently disarm the
        # overlay branch for every test that runs after it.
        self._saved_no_overlay = V._NO_OVERLAY
        self.addCleanup(lambda: setattr(V, "_NO_OVERLAY", self._saved_no_overlay))
        # A skill so the tree looks real; AGENTS.md so the legacy set is non-empty.
        self.write("AGENTS.md", "# contract\n")
        self.write("skills/job-search/SKILL.md", "# job-search\n")

    def write(self, rel: str, text: str) -> Path:
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        return p

    def git_init(self) -> None:
        """Make the temp tree a git checkout so ``git ls-files`` drives the run.

        ``git add -A`` runs HERE, so every file a test wants resolvable must be
        written BEFORE this call. Resolution is against the tracked-path set, not
        ``Path.exists()``, so a planted-but-unadded file reads as absent.
        """
        env = {"GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null",
               "HOME": str(self.root), "PATH": "/usr/bin:/bin:/usr/local/bin"}
        subprocess.run(["git", "init", "-q"], cwd=self.root, check=True, env=env)
        subprocess.run(["git", "add", "-A"], cwd=self.root, check=True, env=env)

    # --- extensions the markdown / overlay / rename cases need ------------------
    def git(self, *args: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
        """Run git in the temp tree (or the overlay) with a hermetic identity."""
        env = {"GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null",
               "HOME": str(self.root), "PATH": "/usr/bin:/bin:/usr/local/bin",
               "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
               "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"}
        return subprocess.run(["git", *args], cwd=str(cwd or self.root),
                              check=True, capture_output=True, text=True, env=env)

    def git_commit(self, message: str = "wip", cwd: Path | None = None) -> None:
        """Stage everything and commit — ``--baseline``/``--compare`` need a HEAD."""
        self.git("add", "-A", cwd=cwd)
        self.git("commit", "-q", "-m", message, cwd=cwd)

    def ignore(self, *patterns: str) -> None:
        """Append to ``.gitignore`` (never clobber — the overlay helper adds too)."""
        p = self.root / ".gitignore"
        prior = p.read_text(encoding="utf-8") if p.exists() else ""
        p.write_text(prior + "".join(f"{x}\n" for x in patterns), encoding="utf-8")

    def overlay_init(self, files: dict[str, str]) -> Path:
        """Make ``private/`` its OWN git checkout, the way the real overlay is.

        Not a helper for tidiness: ``_instruction_files()`` enumerates overlay
        sources only when ``private/.git`` exists, and ``git ls-files`` in the public
        repo cannot see inside a nested repository. A test that just makes a
        ``private/`` FOLDER proves nothing about the branch under test.

        Call this BEFORE ``git_init()``: it adds ``private/`` to ``.gitignore`` so the
        public ``git add -A`` leaves the nested checkout alone, exactly as the real
        repo does.
        """
        overlay = self.root / "private"
        for rel, text in files.items():
            p = overlay / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8")
        self.ignore("private/")
        self.git("init", "-q", cwd=overlay)
        self.git("add", "-A", cwd=overlay)
        return overlay

    def link_root(self) -> None:
        """A resolving ``.claude/skills`` entry so ``run()`` is not red on symlinks.

        ``check_symlinks()`` fails closed when NO link root exists, so any test that
        asserts on ``run()``'s exit code has to give it one.
        """
        skdir = self.root / ".claude/skills"
        skdir.mkdir(parents=True, exist_ok=True)
        (skdir / "job-search").symlink_to(self.root / "skills/job-search")

    def chdir_to_root(self) -> None:
        """``--baseline PATH`` is opened relative to the PROCESS cwd, not REPO_ROOT.

        Without this a baseline test writes into the real repository while the
        git-ignore guard is evaluated against the temp tree.
        """
        saved = os.getcwd()
        os.chdir(self.root)
        self.addCleanup(os.chdir, saved)

    def run_report(self, **kwargs) -> tuple[int, str]:
        """``run()`` with stdout captured — for the cases that must APPEAR in it."""
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = V.run(**kwargs)
        return rc, buf.getvalue()

    def snapshot(self) -> dict:
        """A ``--baseline``-shaped snapshot of the current tree."""
        return V._snapshot(*V.check_references())


class TestSourceSetWidening(VerifyLinksTestCase):
    """A broken ref in a NON-skill doc is a finding (it used to be invisible)."""

    def setUp(self) -> None:
        super().setUp()
        self.write("docs/handbook/architecture.md",
                   f"| `{BROKEN_REF}` | the renamed script |\n")
        self.write("memory/known-issues/stale.md", f"Repro via `{BROKEN_REF}`.\n")
        self.git_init()

    def test_handbook_and_memory_refs_are_now_checked(self) -> None:
        broken, advisory, permitted, _, _ = V.check_references()
        self.assertEqual(permitted, [])
        # ``memory/known-issues/`` is a PLAN source: a known issue's job is to name
        # the gap between the tree and what should be there, so at least one of its
        # paths is expected not to resolve.
        self.assertEqual([(b["file"], b["ref"]) for b in advisory],
                         [("memory/known-issues/stale.md", BROKEN_REF)])
        self.assertEqual([(b["file"], b["ref"]) for b in broken],
                         [("docs/handbook/architecture.md", BROKEN_REF)])

    def test_legacy_source_set_saw_none_of_them(self) -> None:
        """The 'before' half of the proof: 23 files, so neither doc was opened."""
        original = V._instruction_files
        V._instruction_files = _legacy_instruction_files
        self.addCleanup(lambda: setattr(V, "_instruction_files", original))
        broken, advisory, permitted, _, _ = V.check_references()
        self.assertEqual((broken, advisory, permitted), ([], [], []))

    def test_tracked_md_set_is_used_and_ignores_untracked(self) -> None:
        # Written AFTER git_init(), so it is deliberately untracked.
        self.write("docs/handbook/scratch-untracked.md", f"`{BROKEN_REF}`\n")
        names = {p.relative_to(self.root).as_posix() for p in V._instruction_files()}
        self.assertIn("docs/handbook/architecture.md", names)
        self.assertIn("memory/known-issues/stale.md", names)
        self.assertNotIn("docs/handbook/scratch-untracked.md", names)


class TestPlanAndRecordSourcesNeverFailTheGate(VerifyLinksTestCase):
    """Plans and records name target/past paths on purpose — never a hard failure.

    Was ``TestPlanAndRecordSourcesAreAdvisory``, when both kinds landed in one
    ``advisory`` bucket. They are now separate tiers — a plan is ADVISORY (repair it
    when the named thing exists today under another name), a dated record is
    PERMITTED (rewriting it would falsify the record) — and the intent it pinned,
    that neither reddens the gate, is unchanged.
    """

    def test_design_task_and_adr_refs_do_not_fail_the_gate(self) -> None:
        self.write("docs/designs/x/execution-plan.md", f"Create `{BROKEN_REF}`.\n")
        self.write("tasks/0_backlog/2026-01-01-x/task.md", f"Produce `{BROKEN_REF}`.\n")
        self.write("memory/decisions/x.md", f"`{BROKEN_REF}` was dissolved.\n")
        self.git_init()
        broken, advisory, permitted, _, _ = V.check_references()
        self.assertEqual(broken, [])
        self.assertEqual(sorted(b["file"] for b in advisory),
                         ["docs/designs/x/execution-plan.md",
                          "tasks/0_backlog/2026-01-01-x/task.md"])
        self.assertEqual([b["file"] for b in permitted], ["memory/decisions/x.md"])

    def test_handbook_is_not_treated_as_a_plan(self) -> None:
        self.write("docs/handbook/x.md", f"`{BROKEN_REF}`\n")
        self.git_init()
        broken, advisory, permitted, _, _ = V.check_references()
        self.assertEqual(len(broken), 1)
        self.assertEqual((advisory, permitted), ([], []))


class TestAbsentStrictRoots(VerifyLinksTestCase):
    """A strict prefix is strict only in a tree that HAS that root.

    The published export ships no ``memory/``, ``tasks/``, ``message-queue/``,
    ``docs/roadmap/`` or ``history/`` while AGENTS.md and the handbook necessarily name
    them; making them strict everywhere would turn the PUBLISHED repo's gardener
    red — the same trap the reconciler's missing-root no-op exists to avoid.
    """

    def test_ref_into_a_root_this_tree_lacks_is_skipped(self) -> None:
        self.write("docs/handbook/x.md", "See `memory/decisions/whatever.md`.\n")
        self.git_init()
        broken, advisory, permitted, skipped, unrecognised = V.check_references()
        self.assertEqual((broken, advisory, permitted), ([], [], []))
        self.assertEqual(skipped["absent-root"], 1)
        # An absent ROOT is its own class — it must not be laundered through the
        # unrecognised-root bucket, which means something different (§3).
        self.assertEqual(skipped["unrecognised-root"], 0)
        self.assertEqual(unrecognised, [])

    def test_same_ref_is_enforced_once_the_root_exists(self) -> None:
        self.write("docs/handbook/x.md", "See `memory/decisions/whatever.md`.\n")
        self.write("memory/decisions/other.md", "# other\n")
        self.git_init()
        broken, _, _, skipped, _ = V.check_references()
        self.assertEqual([b["ref"] for b in broken], ["memory/decisions/whatever.md"])
        self.assertEqual(skipped["absent-root"], 0)


class TestGitIgnoredRefs(VerifyLinksTestCase):
    """A git-ignored path exists only in some checkouts — never a claim."""

    def test_ignored_ref_is_skipped(self) -> None:
        self.write(".gitignore", "skills/hidden-practice\n")
        self.write("docs/handbook/x.md", "The private `skills/hidden-practice/SKILL.md`.\n")
        self.git_init()
        broken, _, _, skipped, _ = V.check_references()
        self.assertEqual(broken, [])
        self.assertEqual(skipped["git-ignored"], 1)

    def test_overlay_refs_are_not_swallowed_by_the_ignore_rule(self) -> None:
        """``private/**`` is git-ignored wholesale — the overlay branch owns it."""
        (self.root / "private/docs").mkdir(parents=True)
        self.write(".gitignore", "private/\n")
        self.write("docs/handbook/x.md", "See `private/docs/gone.md`.\n")
        self.git_init()
        broken, _, _, skipped, _ = V.check_references()
        self.assertEqual([b["ref"] for b in broken], ["private/docs/gone.md"])
        self.assertEqual(skipped["git-ignored"], 0)


class TestNoGitFallback(VerifyLinksTestCase):
    """Not a git checkout (exported tarball): walk, minus ignored/data trees."""

    def test_walk_skips_private_and_tmp(self) -> None:
        self.write("docs/handbook/x.md", "ok\n")
        self.write("private/secret.md", "ok\n")
        self.write("local/scratch/x.md", "ok\n")
        names = {p.relative_to(self.root).as_posix() for p in V._instruction_files()}
        self.assertIn("docs/handbook/x.md", names)
        self.assertNotIn("private/secret.md", names)
        self.assertNotIn("local/scratch/x.md", names)


class TestSymlinkRootsFailClosed(VerifyLinksTestCase):
    """check_symlinks() must not report success after verifying nothing."""

    def test_zero_link_roots_is_a_finding(self) -> None:
        self.assertFalse((self.root / ".agents/skills").exists())
        self.assertFalse((self.root / ".claude/skills").exists())
        self.assertFalse((self.root / ".cursor/skills").exists())
        bad = V.check_symlinks()
        self.assertEqual(len(bad), 1)
        self.assertIn("NO skill link root", bad[0]["target"])

    def test_present_root_with_resolving_link_passes(self) -> None:
        skdir = self.root / ".claude/skills"
        skdir.mkdir(parents=True)
        (skdir / "job-search").symlink_to(self.root / "skills/job-search")
        self.assertEqual(V.check_symlinks(), [])

    def test_dangling_link_is_a_finding(self) -> None:
        skdir = self.root / ".cursor/skills"
        skdir.mkdir(parents=True)
        (skdir / "gone").symlink_to(self.root / "skills/gone")
        bad = V.check_symlinks()
        self.assertEqual(len(bad), 1)
        self.assertEqual(bad[0]["link"], ".cursor/skills/gone")

    def test_empty_link_root_is_a_finding(self) -> None:
        """A root that exists but holds no symlinks also verified nothing."""
        (self.root / ".claude/skills").mkdir(parents=True)
        bad = V.check_symlinks()
        self.assertEqual([b["link"] for b in bad], [".claude/skills"])
        self.assertIn("no skill symlinks", bad[0]["target"])

    def test_tracked_root_missing_from_the_worktree_is_a_finding(self) -> None:
        skdir = self.root / ".claude/skills"
        skdir.mkdir(parents=True)
        (skdir / "job-search").symlink_to(self.root / "skills/job-search")
        self.git_init()
        shutil.rmtree(self.root / ".claude")
        bad = V.check_symlinks()
        links = [b["link"] for b in bad]
        self.assertIn(".claude/skills", links)
        self.assertIn("TRACKED in git", bad[0]["target"])


class TestReferencesPrivateIsOptional(VerifyLinksTestCase):
    """``references_private/`` is overlay-only and per-user — never a claim.

    Docs still name the pattern with a ``skills/<skill>/references_private/``
    shape even though the folder itself now lives at
    ``config.skill_references_dir("<skill>")``; either spelling must stay
    unresolvable-but-not-broken.
    """

    def test_not_checkable(self) -> None:
        self.assertFalse(V._is_checkable("skills/resume-writer/references_private/"))
        self.assertTrue(V._is_checkable("skills/resume-writer/reference.md"))


class TestMarkdownLinksAreChecked(VerifyLinksTestCase):
    """Hyperlinks are references too — they used to be read by nothing at all.

    Before this, ``[text](path)`` was invisible: only backticked tokens were
    extracted, so every clickable link in the tree was unverified while the report
    said "references: all resolve". These pin both halves — that a link IS checked,
    and that the four things which merely LOOK like links (code spans, fences,
    placeholders, undefined reference labels) are not.
    """

    def test_relative_link_to_a_missing_file_is_broken(self) -> None:
        self.write("docs/handbook/x.md", "See [a](gone.md).\n")
        self.git_init()
        broken, _, _, _, _ = V.check_references()
        self.assertEqual([(b["file"], b["ref"], b["kind"]) for b in broken],
                         [("docs/handbook/x.md", "gone.md", "inline")])

    def test_relative_link_that_resolves_is_not_a_finding(self) -> None:
        self.write("docs/handbook/x.md", "See [a](../../AGENTS.md).\n")
        self.git_init()
        broken, advisory, permitted, _, _ = V.check_references()
        self.assertEqual((broken, advisory, permitted), ([], [], []))

    def test_link_inside_an_inline_code_span_is_not_a_link(self) -> None:
        """15 of the 40 raw findings were this shape: docs ABOUT markdown links."""
        self.write("docs/handbook/x.md", "Write it as `[a](gone.md)` in prose.\n")
        self.git_init()
        broken, advisory, permitted, _, _ = V.check_references()
        self.assertEqual((broken, advisory, permitted), ([], [], []))

    def test_link_inside_a_fenced_block_is_not_a_link(self) -> None:
        self.write("docs/handbook/x.md",
                   "Example:\n\n```markdown\n[a](gone.md)\n```\n\ntail\n")
        self.git_init()
        broken, _, _, _, _ = V.check_references()
        self.assertEqual(broken, [])

    def test_code_span_may_open_on_one_line_and_close_on_the_next(self) -> None:
        """The one case a per-line stripper cannot pass.

        A line-by-line mask handles every other test in this class and fails only
        here — and the real instances live in ``docs/handbook/doc-style.md``, a
        hard-fail source, so getting this wrong is a permanent commit blocker rather
        than noise. The mask therefore runs over the whole document with DOTALL.
        """
        self.write("docs/handbook/x.md",
                   "The shape `[a](gone.md) and\n"
                   "[b](also-gone.md)` is illustrative.\n")
        self.git_init()
        broken, advisory, permitted, _, _ = V.check_references()
        self.assertEqual((broken, advisory, permitted), ([], [], []))

    @unittest.expectedFailure
    def test_link_inside_an_indented_code_block_is_not_a_link(self) -> None:
        """DESIGN §1d step 2 — NOT implemented; this is an expected failure.

        The masking contract requires CommonMark indented code blocks (4 spaces after
        a blank line) to be blanked alongside fences, HTML comments and spans.
        ``_mask_fences()`` handles fences and comments only, so an illustrative link
        indented rather than fenced is reported broken — in whatever tier its source
        document sits, which for ``docs/handbook/`` is fatal. Flips to an UNEXPECTED
        SUCCESS when the module grows step 2.
        """
        self.write("docs/handbook/x.md", "Example:\n\n    [a](gone.md)\n\ntail\n")
        self.git_init()
        broken, _, _, _, _ = V.check_references()
        self.assertEqual(broken, [])

    def test_placeholder_destination_is_counted_not_resolved(self) -> None:
        """``templates/`` is full of ``[<source>](<relative path to …>)``."""
        self.write("templates/queue/decision.md", "[<src>](<relative path>)\n")
        self.git_init()
        broken, advisory, permitted, skipped, _ = V.check_references()
        self.assertEqual((broken, advisory, permitted), ([], [], []))
        self.assertEqual(skipped["placeholder"], 1)

    def test_image_destination_is_checked(self) -> None:
        self.write("docs/handbook/x.md", "![img](gone.png)\n")
        self.git_init()
        broken, _, _, _, _ = V.check_references()
        self.assertEqual([(b["ref"], b["kind"]) for b in broken],
                         [("gone.png", "image")])

    def test_reference_style_link_is_reported_at_its_definition(self) -> None:
        """The definition is the line a repairer edits, not the use site.

        Exactly one reference-style link exists across both trees, and it sits inside
        the overlay's interview tree — a checker that handles only ``[t](d)`` drops it
        silently.
        """
        self.write("docs/handbook/x.md",
                   "intro\n"
                   "The [a][ref] shape.\n"
                   "more prose\n"
                   "[ref]: gone.md\n")
        self.git_init()
        broken, _, _, _, _ = V.check_references()
        self.assertEqual([(b["line"], b["kind"], b["ref"]) for b in broken],
                         [(4, "reference", "gone.md")])

    def test_undefined_reference_label_is_not_a_finding(self) -> None:
        """CommonMark: ``[a][b]`` with no ``[b]:`` renders as LITERAL TEXT.

        Reporting it looks principled and is wrong — ``dp[i][j]`` in algorithm notes
        matches the same shape, and the version that reported undefined labels
        produced 31 phantom findings inside the overlay's coding notes alone, dead
        centre in the tree the repair phase has to prove clean.
        """
        self.write("docs/handbook/x.md",
                   "Fill dp[i][j] from dp[i-1][j] and dp[i][j-1].\n")
        self.git_init()
        broken, advisory, permitted, _, unrecognised = V.check_references()
        self.assertEqual((broken, advisory, permitted, unrecognised), ([], [], [], []))

    def test_external_url_is_counted_never_fetched(self) -> None:
        """No network in the gate: an HTTP-fetching checker is a weather report."""
        self.write("docs/handbook/x.md", "See [a](https://example.invalid/x).\n")
        self.git_init()
        broken, _, _, skipped, _ = V.check_references()
        self.assertEqual(broken, [])
        self.assertEqual(skipped["external"], 1)

    def test_markdown_links_do_not_inherit_the_backtick_base_list(self) -> None:
        """A link resolves against its OWN directory only — it is what a reader clicks.

        ``_bases_for()`` gives backticks the repo root, the skill root and
        ``skills/*/scripts/``. Extending that to links would pass a hyperlink that
        404s on GitHub.
        """
        self.write("docs/handbook/x.md", "See [a](scripts/status.py).\n")
        self.write("skills/s/scripts/status.py", "# real, but not from here\n")
        self.git_init()
        broken, _, _, _, _ = V.check_references()
        self.assertEqual([(b["ref"], b["target"]) for b in broken],
                         [("scripts/status.py", "docs/handbook/scripts/status.py")])
        self.assertIn("own directory only", broken[0]["why"])

    def test_the_same_string_can_be_fine_in_backticks_and_broken_as_a_link(self) -> None:
        """The deliberate asymmetry, pinned so it reads as design and not as a bug.

        In one skill doc, ``t/SKILL.md`` in backticks resolves against the skills
        root; the identical string as a hyperlink resolves against ``skills/s/`` and
        does not exist. Both verdicts are correct — a backtick is a name, a link is a
        hyperlink — and this is the surprise the failure message exists to explain.
        """
        self.write("skills/s/reference.md",
                   "Prose shorthand: `t/SKILL.md`.\n\nHyperlink: [t](t/SKILL.md).\n")
        self.write("skills/t/SKILL.md", "# t\n")
        self.git_init()
        broken, _, _, _, _ = V.check_references()
        self.assertEqual([(b["kind"], b["ref"]) for b in broken],
                         [("inline", "t/SKILL.md")])

    def test_case_only_difference_is_broken_even_on_a_case_blind_filesystem(self) -> None:
        """Resolution is the tracked-path SET, not ``Path.exists()``.

        macOS accepts ``../ARCHITECTURE.md`` for ``architecture.md`` and Linux CI does
        not; this repo has shipped that break once. The tracked set is case-exact and
        already computed, so the finding is filesystem-independent.
        """
        self.write("docs/handbook/GONE.md", "# the real, differently-cased file\n")
        self.write("docs/handbook/x.md", "See [a](gone.md).\n")
        self.git_init()
        broken, _, _, _, _ = V.check_references()
        self.assertEqual([b["target"] for b in broken], ["docs/handbook/gone.md"])

    def test_html_href_and_src_are_checked(self) -> None:
        """Cheap insurance: none exist today, and raw HTML in a doc is still a link."""
        self.write("docs/handbook/x.md",
                   '<a href="gone.md">t</a> and <img src="gone.png">\n')
        self.git_init()
        broken, _, _, _, _ = V.check_references()
        self.assertEqual(sorted(b["ref"] for b in broken), ["gone.md", "gone.png"])
        self.assertEqual({b["kind"] for b in broken}, {"html"})

    def test_link_inside_an_html_comment_is_not_a_link(self) -> None:
        self.write("docs/handbook/x.md", "before\n<!--\n[a](gone.md)\n-->\nafter\n")
        self.git_init()
        broken, _, _, _, _ = V.check_references()
        self.assertEqual(broken, [])

    def test_link_escaping_the_repository_root_is_a_finding(self) -> None:
        self.write("docs/handbook/x.md", "See [a](../../../outside.md).\n")
        self.git_init()
        broken, _, _, _, _ = V.check_references()
        self.assertEqual(len(broken), 1)
        self.assertIn("escapes the repository root", broken[0]["why"])


class TestMarkdownLinkTiers(VerifyLinksTestCase):
    """A break's fate comes from what its SOURCE document is for, never its target.

    Reference sources fail, plans are advisory, dated records are permitted — and the
    default is the strict one, so a folder nobody has classified fails CLOSED.
    """

    def test_each_source_tree_lands_in_its_own_bucket(self) -> None:
        link = "See [a](gone.md).\n"
        self.write("docs/handbook/x.md", link)
        self.write("docs/designs/x/README.md", link)
        self.write("tasks/0_backlog/2026-01-01-x/task.md", link)
        self.write("tasks/4_done/2026-01-01-x/task.md", link)
        self.write("history/conversations/2026-01-01-x/handover.md", link)
        self.write("memory/decisions/x.md", link)
        self.git_init()
        broken, advisory, permitted, _, _ = V.check_references()
        self.assertEqual([b["file"] for b in broken], ["docs/handbook/x.md"])
        self.assertEqual(sorted(b["file"] for b in advisory),
                         ["docs/designs/x/README.md",
                          "tasks/0_backlog/2026-01-01-x/task.md"])
        self.assertEqual(sorted(b["file"] for b in permitted),
                         ["history/conversations/2026-01-01-x/handover.md",
                          "memory/decisions/x.md",
                          "tasks/4_done/2026-01-01-x/task.md"])

    def test_an_unknown_task_status_folder_fails_closed(self) -> None:
        """The five status folders are enumerated instead of a blanket ``tasks/``.

        With a bare ``tasks/`` prefix every status folder — including one invented
        tomorrow — silently inherited advisory. A status folder nobody has taught this
        checker about now defaults to REFERENCE and reddens the gate.
        """
        self.write("tasks/9_invented-status/x/task.md", "See [a](gone.md).\n")
        self.git_init()
        broken, advisory, permitted, _, _ = V.check_references()
        self.assertEqual([b["file"] for b in broken],
                         ["tasks/9_invented-status/x/task.md"])
        self.assertEqual((advisory, permitted), ([], []))

    def test_the_five_handover_case_is_permitted_and_still_printed(self) -> None:
        """The exact live shape: 5 handovers naming a queue file that was folded away.

        The queue item became ``memory/decisions/config-discovery-example-fallback.md``
        and the handovers were true when written, so rewriting them would falsify the
        record. They must be PERMITTED, must not fail the gate — and must still appear
        in the report, because the one thing a permitted break may not do is vanish.
        Asserted on stdout rather than the return value for exactly that reason.
        """
        dead = ("../../../message-queue/needs-human/decisions/"
                "config-discovery-example-fallback.md")
        names = ["2026-07-24-hygiene-stack", "2026-07-25-private-application-draft",
                 "2026-07-26-workspace-phase-1", "2026-07-27-workspace-phase-2",
                 "2026-07-29-workspace-phases-0-3-4"]
        for name in names:
            self.write(f"history/conversations/{name}/handover.md",
                       f"Folded [the decision]({dead}).\n")
        self.write("memory/decisions/config-discovery-example-fallback.md",
                   "# ADR\n\nSupersedes the queue item of the same name.\n")
        self.link_root()
        self.git_init()

        broken, advisory, permitted, _, _ = V.check_references()
        self.assertEqual((broken, advisory), ([], []))
        self.assertEqual(len(permitted), 5)

        rc, out = self.run_report()
        self.assertEqual(rc, 0)
        for name in names:
            self.assertIn(f"history/conversations/{name}/handover.md", out)

        tracked_pub, _ = V._tracked_set()
        self.assertEqual(
            V._suggest("message-queue/needs-human/decisions/"
                       "config-discovery-example-fallback.md", tracked_pub, {}),
            "memory/decisions/config-discovery-example-fallback.md")


class TestUnrecognisedRootIsCounted(VerifyLinksTestCase):
    """The hole that had no counter at all.

    A backticked token that is neither strict nor absent used to fall through the
    ``if/elif`` with nothing incremented. Renaming a root migrates references into
    that hole one at a time and NOTHING said so — the ``handbook/`` →
    ``docs/handbook/`` rename moved ~19 of them in silence. It stays non-fatal (most
    are prose shorthand, branch names or API paths) but it is never invisible again,
    and the baseline compare turns the tally into the detector.
    """

    def test_retired_root_is_counted_and_not_broken(self) -> None:
        self.write("docs/handbook/x.md",
                   "See `handbook/definitely-not-a-real-file.md`.\n")
        self.git_init()
        broken, advisory, permitted, skipped, unrecognised = V.check_references()
        self.assertEqual((broken, advisory, permitted), ([], [], []))
        self.assertEqual(skipped["unrecognised-root"], 1)
        self.assertEqual([u["ref"] for u in unrecognised],
                         ["handbook/definitely-not-a-real-file.md"])

    def test_the_paired_control_under_a_live_root_is_broken(self) -> None:
        """Same file, same basename — only the ROOT differs, and that is the point."""
        self.write("docs/handbook/x.md",
                   "See `docs/handbook/definitely-not-a-real-file.md`.\n")
        self.git_init()
        broken, _, _, skipped, unrecognised = V.check_references()
        self.assertEqual([b["ref"] for b in broken],
                         ["docs/handbook/definitely-not-a-real-file.md"])
        self.assertEqual(skipped["unrecognised-root"], 0)
        self.assertEqual(unrecognised, [])

    def test_a_branch_name_is_counted_not_broken(self) -> None:
        """185 of the 621 live tokens come from reference docs and none is stale.

        They are branch names, Graph endpoints, ``BS/MS/PhD``-style enumerations and
        table shorthand. Making the class fatal needs a hand-maintained allowlist of
        exactly the kind this checker refuses to grow.
        """
        self.write("CONTRIBUTING.md", "Branch from `fix/some-branch`.\n")
        self.git_init()
        broken, _, _, skipped, unrecognised = V.check_references()
        self.assertEqual(broken, [])
        self.assertEqual(skipped["unrecognised-root"], 1)
        self.assertFalse(unrecognised[0]["names_a_file"])

    def test_names_a_file_split_makes_the_tally_readable(self) -> None:
        """621 is unreadable; "of which 126 name a file" concentrates the damage."""
        self.write("docs/handbook/x.md", "Both `handbook/x.md` and `handbook/`.\n")
        self.git_init()
        _, _, _, skipped, unrecognised = V.check_references()
        self.assertEqual(skipped["unrecognised-root"], 2)
        self.assertEqual(sorted(u["ref"] for u in unrecognised),
                         ["handbook/", "handbook/x.md"])
        self.assertEqual(sum(1 for u in unrecognised if u["names_a_file"]), 1)


class TestOverlayAndSkipTreesForMarkdownLinks(VerifyLinksTestCase):
    """Targets that this checkout cannot resolve are COUNTED, never asserted."""

    def test_link_into_an_unmounted_overlay_is_skipped(self) -> None:
        """The CI-green requirement, and it is live rather than hypothetical.

        ``evals/README.md`` and ``evals/protocols/ab-protocol.md`` both link into
        ``private/docs/``, both are reference-tier, and ``evals/`` is in the public
        exporter's allowlist. Without this branch the first CI run after markdown
        links were switched on is red.
        """
        self.write("evals/README.md", "See [a](../private/docs/gone.md).\n")
        self.git_init()
        broken, advisory, permitted, skipped, _ = V.check_references()
        self.assertEqual((broken, advisory, permitted), ([], [], []))
        self.assertEqual(skipped["overlay"], 1)

    def test_the_same_link_is_enforced_once_the_overlay_is_mounted(self) -> None:
        self.write("evals/README.md", "See [a](../private/docs/gone.md).\n")
        self.overlay_init({"docs/present.md": "# present\n"})
        self.git_init()
        broken, _, _, skipped, _ = V.check_references()
        self.assertEqual([(b["file"], b["target"]) for b in broken],
                         [("evals/README.md", "private/docs/gone.md")])
        self.assertEqual(skipped["overlay"], 0)

    def test_a_mounted_overlay_target_that_exists_resolves(self) -> None:
        """Resolution inside the overlay reads the OVERLAY's tracked set, not disk."""
        self.write("evals/README.md", "See [a](../private/docs/present.md).\n")
        self.overlay_init({"docs/present.md": "# present\n"})
        self.git_init()
        broken, advisory, permitted, _, _ = V.check_references()
        self.assertEqual((broken, advisory, permitted), ([], [], []))

    def test_link_into_a_runtime_data_tree_is_skipped(self) -> None:
        self.write("evals/README.md", "See [a](../applications/x/meta.yaml).\n")
        self.git_init()
        broken, _, _, skipped, _ = V.check_references()
        self.assertEqual(broken, [])
        self.assertEqual(skipped["skip-tree"], 1)


class TestOverlaySourcesAreEnumerated(VerifyLinksTestCase):
    """The overlay is a SEPARATE git repository, so its docs were never read.

    ``_instruction_files()`` ran ``git ls-files`` in the public repo, which cannot see
    inside a nested checkout: ~1000 tracked overlay ``.md`` — and every link in them —
    had never been read by this routine. ``SKIP_PREFIXES`` filters TOKENS NAMED IN
    public docs; it never filtered which FILES are opened, so removing an entry from
    it makes no overlay file visible.
    """

    def test_overlay_tiers_apply_after_stripping_the_prefix(self) -> None:
        """The overlay mirrors the same process layer, so it gets the same rule."""
        link = "See [a](gone.md).\n"
        self.overlay_init({"docs/designs/x/README.md": link,
                           "tasks/4_done/x/task.md": link,
                           "memory/decisions/x.md": link,
                           "docs/handbook/x.md": link})
        self.git_init()
        broken, advisory, permitted, _, _ = V.check_references()
        self.assertEqual([b["file"] for b in broken], ["private/docs/handbook/x.md"])
        self.assertEqual([b["file"] for b in advisory],
                         ["private/docs/designs/x/README.md"])
        self.assertEqual(sorted(b["file"] for b in permitted),
                         ["private/memory/decisions/x.md",
                          "private/tasks/4_done/x/task.md"])
        self.assertEqual({b["tier"] for b in broken}, {"reference"})

    def test_a_broken_link_inside_the_overlay_interview_tree_is_fatal(self) -> None:
        """Design §5b, and the reason the whole overlay-enumeration work exists.

        "A repair that cannot turn the gate red is not verifiable." When this test
        was written it was an EXPECTED FAILURE: the module still carried
        ``private/interviews/`` in ``SKIP_PREFIXES``, so a broken link inside that
        tree was tallied ``skip-tree`` and the phase-5 repair could not be checked.

        Workspace phase 5 dissolved that tree into ``companies/`` and
        ``me/interviews/`` and dropped the prefix, and this flipped to an unexpected
        success in the same run — which is exactly what an expected-failure marker is
        for. It is now an ordinary assertion, and it stays here rather than being
        deleted with the directory: it pins the RULE (an overlay path matching no
        plan or record prefix is reference tier, therefore fatal), not the one
        directory that motivated it.
        """
        self.overlay_init({"interviews/a/notes.md": "See [a](../b/gone.md).\n"})
        self.git_init()
        broken, _, _, _, _ = V.check_references()
        self.assertEqual([(b["file"], b["tier"]) for b in broken],
                         [("private/interviews/a/notes.md", "reference")])

    def test_an_overlay_data_tree_is_still_skipped_not_reported(self) -> None:
        """The other half of the rule: ``applications/`` and ``local/`` stay skipped.

        Replaces a companion test that pinned ``private/interviews/`` being tallied
        ``skip-tree``. That behaviour was correct until phase 5 and is now wrong, so
        the assertion moves to a tree that IS still runtime data. The file is still
        enumerated and read either way — the source-set half of the fix is what makes
        the tier decision meaningful at all.
        """
        self.overlay_init({"applications/6_drafted/x/notes.md": "See [a](../b/gone.md).\n"})
        self.git_init()
        broken, advisory, permitted, skipped, _ = V.check_references()
        self.assertEqual((broken, advisory, permitted), ([], [], []))
        self.assertEqual(skipped["skip-tree"], 1)
        self.assertIn("private/applications/6_drafted/x/notes.md",
                      [V._rel(f) for f in V._instruction_files()])

    def test_removing_the_overlay_reproduces_the_public_result_exactly(self) -> None:
        """The CI assertion: with no ``private/`` every count is what it was before.

        Compared against ``--no-overlay`` on the identical tree, because the flag has
        to reproduce a contributor checkout rather than half of one.
        """
        self.write("docs/handbook/x.md", "See [a](gone.md).\n")
        self.overlay_init({"docs/handbook/y.md": "See [a](also-gone.md).\n"})
        self.git_init()

        with_overlay = V.check_references()
        self.assertEqual(sorted(b["file"] for b in with_overlay[0]),
                         ["docs/handbook/x.md", "private/docs/handbook/y.md"])

        V._NO_OVERLAY = True
        flagged = V.check_references()
        V._NO_OVERLAY = False
        shutil.rmtree(self.root / "private")
        removed = V.check_references()

        self.assertEqual(flagged, removed)
        self.assertEqual([b["file"] for b in removed[0]], ["docs/handbook/x.md"])

    def test_no_overlay_flag_shrinks_the_source_set_to_the_public_one(self) -> None:
        self.write("docs/handbook/x.md", "ok\n")
        self.overlay_init({"docs/handbook/y.md": "ok\n"})
        self.git_init()
        self.assertIn("private/docs/handbook/y.md",
                      [V._rel(f) for f in V._instruction_files()])
        V._NO_OVERLAY = True
        self.assertEqual([V._rel(f) for f in V._instruction_files()],
                         ["AGENTS.md", "docs/handbook/x.md",
                          "skills/job-search/SKILL.md"])

    def test_baseline_refuses_a_tracked_destination_when_overlay_files_were_read(self) -> None:
        """A baseline naming overlay files is a machine-readable list of private paths.

        One ``git add -A`` away from the public remote is not a risk to discourage; the
        write is refused outright unless git ignores the destination.
        """
        self.chdir_to_root()
        self.write("docs/handbook/x.md", "See [a](gone.md).\n")
        self.overlay_init({"docs/handbook/y.md": "See [a](also-gone.md).\n"})
        self.ignore("local/")
        self.link_root()
        self.git_init()

        rc, out = self.run_report(baseline="docs/links.json")
        self.assertEqual(rc, 1)
        self.assertIn("REFUSED", out)
        self.assertFalse((self.root / "docs/links.json").exists())

    def test_baseline_to_a_git_ignored_destination_is_written(self) -> None:
        self.chdir_to_root()
        self.write("docs/handbook/x.md", "See [a](gone.md).\n")
        self.overlay_init({"docs/handbook/y.md": "See [a](also-gone.md).\n"})
        self.ignore("local/")
        self.link_root()
        self.git_init()
        self.git_commit()
        self.git_commit(cwd=self.root / "private")

        _, out = self.run_report(baseline="local/links.json")
        self.assertIn("baseline written", out)
        data = json.loads((self.root / "local/links.json").read_text())
        self.assertIsNotNone(data["overlay_commit"])
        self.assertEqual(data["counts"]["broken"], 2)


class TestRootDisappearance(VerifyLinksTestCase):
    """Renaming a root DISARMS a checker instead of breaking it.

    Phase 2 renamed ``handbook/`` to ``docs/handbook/`` and four constants went
    quietly stale: ``_present_strict_prefixes()`` no-ops on a missing root by design
    (that is what keeps the published export green) and the tier lists simply stop
    matching. ``--require-roots`` turns the silent disarm into a loud failure, in
    maintainer checkouts only.
    """

    def make_prefix_roots(self, skip: tuple[str, ...] = ()) -> None:
        """Materialise every directory the module's prefix constants name.

        Reads the constants at CALL time, so a test that patches them first gets a
        tree matching the patched set.
        """
        for prefix in (V.STRICT_ROOT_PREFIXES + V.RECORD_SOURCES + V.PLAN_SOURCES):
            if prefix in skip:
                continue
            rel = prefix.rstrip("/")
            if rel.endswith(".md"):
                self.write(rel, "# placeholder\n")
            else:
                (self.root / rel).mkdir(parents=True, exist_ok=True)

    def plant(self) -> None:
        self.make_prefix_roots(skip=("history/",))
        self.write("docs/handbook/x.md",
                   "See `history/conversations/x/handover.md`.\n")
        self.link_root()
        self.git_init()

    def test_absent_root_is_tolerated_and_counted_without_the_flag(self) -> None:
        """Published-export behaviour: the root was never shipped, so it is not a claim."""
        self.plant()
        broken, _, _, skipped, _ = V.check_references()
        self.assertEqual(broken, [])
        self.assertEqual(skipped["absent-root"], 1)
        rc, _ = self.run_report()
        self.assertEqual(rc, 0)

    def test_require_roots_names_the_stale_constant(self) -> None:
        """"This checkout should have that root and does not" is a failure."""
        self.plant()
        # Asserted as a set: ``history/`` is in BOTH ``STRICT_ROOT_PREFIXES`` and
        # ``RECORD_SOURCES`` and ``check_required_roots()`` concatenates the tuples
        # without de-duplicating, so it is returned twice and the report says
        # "MISSING ROOTS (2)" for one missing directory. Cosmetic, but the set is
        # what this test means — ``history/`` is missing and nothing else is.
        self.assertEqual(sorted(set(V.check_required_roots())), ["history/"])
        rc, out = self.run_report(require_roots=True)
        self.assertEqual(rc, 1)
        self.assertIn("MISSING ROOTS", out)
        self.assertIn("history/", out)

    def test_dropping_the_prefix_from_the_constants_makes_it_green(self) -> None:
        """The supported migration is a one-line constant edit, in the same commit.

        When handovers move to the never-committed ``private/local/history/``, the
        RULE ("dated testimony is permitted") is untouched — only the address moves.
        """
        strict = tuple(p for p in V.STRICT_ROOT_PREFIXES if p != "history/")
        record = tuple(p for p in V.RECORD_SOURCES if p != "history/")
        for name, value in (("STRICT_ROOT_PREFIXES", strict), ("RECORD_SOURCES", record)):
            original = getattr(V, name)
            setattr(V, name, value)
            self.addCleanup(setattr, V, name, original)

        self.plant()
        self.assertEqual(V.check_required_roots(), [])
        rc, _ = self.run_report(require_roots=True)
        self.assertEqual(rc, 0)
        # With ``history/`` gone from the strict list the surviving ref is neither
        # strict nor absent, so it lands in the tally rather than reddening the gate.
        broken, _, _, skipped, _ = V.check_references()
        self.assertEqual(broken, [])
        self.assertEqual(skipped["unrecognised-root"], 1)


class TestAnchors(VerifyLinksTestCase):
    """Heading fragments, and the two slug rules a naive implementation gets wrong."""

    def test_missing_same_document_anchor_is_a_finding(self) -> None:
        self.write("docs/handbook/x.md", "## Present\n\nSee [a](#missing).\n")
        self.git_init()
        broken, _, _, skipped, _ = V.check_references()
        self.assertEqual([(b["kind"], b["ref"]) for b in broken], [("anchor", "#missing")])
        self.assertEqual(skipped["anchor-only"], 1)

    def test_present_same_document_anchor_resolves(self) -> None:
        self.write("docs/handbook/x.md", "## Present\n\nSee [a](#present).\n")
        self.git_init()
        broken, _, _, _, _ = V.check_references()
        self.assertEqual(broken, [])

    def test_whitespace_runs_are_not_collapsed(self) -> None:
        """GitHub maps each whitespace CHARACTER to one hyphen; it does not collapse.

        ``## Merged: phase 2 — public-side cleanup`` slugs to
        ``merged-phase-2--public-side-cleanup`` because dropping the em dash leaves
        two spaces. A ``re.sub(r"\\s+", "-")`` yields one hyphen and reports nine
        healthy links as broken.
        """
        self.write("docs/handbook/x.md",
                   "## Merged: phase 2 — public-side cleanup\n\n"
                   "See [a](#merged-phase-2--public-side-cleanup).\n")
        self.git_init()
        broken, _, _, _, _ = V.check_references()
        self.assertEqual(broken, [])
        self.assertEqual(V._slug("Merged: phase 2 — public-side cleanup"),
                         "merged-phase-2--public-side-cleanup")

    def test_headings_are_read_with_code_spans_intact(self) -> None:
        """The one place the masking contract must NOT be applied.

        Masking spans blanks the backticked text inside a heading and silently changes
        its slug, so heading extraction runs on fences-masked but span-INTACT text.
        """
        self.write("docs/handbook/x.md",
                   "## Phase 5 — inside `private/`\n\n"
                   "See [a](#phase-5--inside-private).\n")
        self.git_init()
        broken, _, _, _, _ = V.check_references()
        self.assertEqual(broken, [])

    def test_duplicate_headings_get_numbered_slugs(self) -> None:
        self.write("docs/handbook/x.md", "## Same\n\n## Same\n\nSee [a](#same-1).\n")
        self.git_init()
        broken, _, _, _, _ = V.check_references()
        self.assertEqual(broken, [])

    def test_cross_file_fragment_is_checked_against_the_target(self) -> None:
        self.write("docs/handbook/y.md", "## Present\n")
        self.write("docs/handbook/x.md", "See [a](y.md#missing) and [b](y.md#present).\n")
        self.git_init()
        broken, _, _, _, _ = V.check_references()
        self.assertEqual([(b["kind"], b["ref"]) for b in broken],
                         [("anchor", "y.md#missing")])

    def test_an_anchor_break_in_a_plan_is_advisory(self) -> None:
        """Anchors are tiered like every other finding — the source decides."""
        self.write("docs/designs/x/README.md", "## Present\n\nSee [a](#missing).\n")
        self.git_init()
        broken, advisory, _, _, _ = V.check_references()
        self.assertEqual(broken, [])
        self.assertEqual([b["kind"] for b in advisory], ["anchor"])


class TestRenameFollowing(VerifyLinksTestCase):
    """``--compare`` must survive a repo-wide move, which is when it is needed most.

    Keying a finding on ``<source> -> <target>`` alone reported "36 repaired, 31
    fresh" after the phase-2 stack moved most source files — every pre-existing break
    reappeared under a new name. Both axes go through git's own rename map first, and
    the target is normalised to a repo-root-relative path so a subtree moving one
    level down changes no key.
    """

    def setUp(self) -> None:
        super().setUp()
        self.write("handbook/a.md", "See [x](gone.md).\n")
        self.git_init()
        self.git_commit("before")
        self.before = self.snapshot()
        self.assertEqual([(r["source"], r["target_norm"])
                          for r in self.before["findings"]],
                         [("handbook/a.md", "handbook/gone.md")])

    def disable_rename_map(self) -> None:
        original = V._rename_map
        V._rename_map = lambda *a, **k: {}
        self.addCleanup(lambda: setattr(V, "_rename_map", original))

    def only_public_rename_map(self) -> None:
        """Simulate the single-map implementation: public renames only."""
        original = V._rename_map

        def patched(root, old, prefix=""):
            return original(root, old, prefix) if root == C.REPO_ROOT else {}

        V._rename_map = patched
        self.addCleanup(lambda: setattr(V, "_rename_map", original))

    def test_a_subtree_move_is_not_a_repo_wide_regression(self) -> None:
        (self.root / "docs").mkdir()
        self.git("mv", "handbook", "docs/handbook")
        self.git_commit("phase-2 rename")
        summary, new = V._compare(self.before, self.snapshot())
        self.assertEqual((summary["new"], summary["unchanged"], summary["resolved"]),
                         (0, 1, 0))
        self.assertEqual(new, [])

    def test_a_pure_directory_move_still_matches_without_the_rename_map(self) -> None:
        """DESIGN §7 expects ``new == 1`` here; §4's tier-3 key absorbs it first.

        §7 says disabling the rename map turns this into "new 1 / resolved 1". It does
        not, because the design's own third key is ``(basename(source),
        basename(target))`` and a directory move changes neither basename. The map is
        genuinely load-bearing only when a basename moves too — the next test. This
        one is here so the discrepancy is recorded rather than rediscovered, and it
        asserts ``matched_loosely`` so the mechanism is visible in the report.
        """
        self.disable_rename_map()
        (self.root / "docs").mkdir()
        self.git("mv", "handbook", "docs/handbook")
        self.git_commit("phase-2 rename")
        summary, new = V._compare(self.before, self.snapshot())
        self.assertEqual((summary["new"], summary["unchanged"]), (0, 1))
        self.assertEqual(summary["matched_loosely"], 1)
        self.assertEqual(new, [])

    def test_the_rename_map_is_what_survives_a_basename_change(self) -> None:
        """Move the file AND rename it: only git's rename detection connects the two."""
        (self.root / "docs/handbook").mkdir(parents=True)
        self.git("mv", "handbook/a.md", "docs/handbook/renamed.md")
        self.git_commit("moved and renamed")

        after = self.snapshot()
        summary, _ = V._compare(self.before, after)
        self.assertEqual((summary["new"], summary["unchanged"]), (0, 1))

        self.disable_rename_map()
        summary, new = V._compare(self.before, after)
        self.assertEqual((summary["new"], summary["resolved"]), (1, 1))
        self.assertEqual([r["source"] for r in new], ["docs/handbook/renamed.md"])

    def test_moving_the_target_instead_of_the_source_also_matches(self) -> None:
        """The source stays put and its destination string follows a real move."""
        self.write("docs/handbook/a.md", "See [x](../designs/gone.md).\n")
        self.write("docs/designs/README.md", "# a real file that will move\n")
        (self.root / "handbook/a.md").unlink()
        self.git_commit("target-side setup")
        before = self.snapshot()
        self.assertEqual([r["target_norm"] for r in before["findings"]],
                         ["docs/designs/gone.md"])

        self.git("mv", "docs/designs", "docs/plans")
        self.write("docs/handbook/a.md", "See [x](../plans/gone.md).\n")
        self.git_commit("target moved, link followed")

        summary, new = V._compare(before, self.snapshot())
        self.assertEqual((summary["new"], summary["unchanged"]), (0, 1))
        self.assertEqual(new, [])

    def test_a_genuinely_new_break_after_a_move_is_reported(self) -> None:
        (self.root / "docs").mkdir()
        self.git("mv", "handbook", "docs/handbook")
        self.write("docs/handbook/b.md", "See [x](also-gone.md).\n")
        self.git_commit("rename plus a fresh break")
        summary, new = V._compare(self.before, self.snapshot())
        self.assertEqual(summary["new"], 1)
        self.assertEqual([(r["source"], r["target_raw"]) for r in new],
                         [("docs/handbook/b.md", "also-gone.md")])

    def test_a_move_git_records_as_delete_plus_add_matches_loosely(self) -> None:
        """A heavy rewrite defeats git's similarity index; the loose keys catch it.

        A run whose findings match only at the loose tier is telling the reader the
        rename map was unreliable and the numbers need eyes — which is why the count
        is reported rather than swallowed.
        """
        (self.root / "handbook/a.md").unlink()
        self.write("docs/handbook/a.md",
                   "\n".join(f"Wholly different sentence number {i} about "
                             f"unrelated subject matter." for i in range(60))
                   + "\n\nSee [x](gone.md).\n")
        self.git_commit("delete plus add")
        renames = V._rename_map(self.root, self.before["commit"])
        self.assertNotIn("handbook/a.md", renames)  # git saw no rename

        summary, new = V._compare(self.before, self.snapshot())
        self.assertEqual((summary["new"], summary["unchanged"]), (0, 1))
        self.assertEqual(summary["matched_loosely"], 1)
        self.assertEqual(new, [])

    def test_a_rename_inside_the_overlay_repo_needs_its_own_map(self) -> None:
        """Two rename maps, because the overlay is a separate repository.

        A single-map implementation reports every moved overlay file as a fresh break
        — which is precisely the repair phase's shape, a large move inside
        ``private/``.
        """
        overlay = self.overlay_init({"docs/a.md": "See [x](gone.md).\n"})
        self.git_commit("mount overlay")
        self.git_commit("overlay baseline", cwd=overlay)

        before = self.snapshot()
        self.assertIsNotNone(before["overlay_commit"])
        self.assertIn(("private/docs/a.md", "private/docs/gone.md"),
                      [(r["source"], r["target_norm"]) for r in before["findings"]])

        (overlay / "newdocs").mkdir()
        self.git("mv", "docs/a.md", "newdocs/renamed.md", cwd=overlay)
        self.git_commit("overlay move", cwd=overlay)

        after = self.snapshot()
        summary, new = V._compare(before, after)
        self.assertEqual(summary["new"], 0)
        self.assertEqual(new, [])

        self.only_public_rename_map()
        summary, new = V._compare(before, after)
        self.assertEqual(summary["new"], 1)
        self.assertEqual([r["source"] for r in new], ["private/newdocs/renamed.md"])


if __name__ == "__main__":
    unittest.main()
