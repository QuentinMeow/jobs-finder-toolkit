"""Tests for the eval-record content pins.

Run with (from the repo root):
    .venv/bin/python -m unittest discover -s automation/evals/tests

Every test builds a throwaway tree — and, where a revision is needed, a throwaway
git repository — so nothing here reads this checkout (or the private overlay).

What is pinned here:
  * ``--emit`` is DETERMINISTIC. The block is the record's evidence; two emits of
    the same bytes that differ in ordering or formatting would make a diff between
    two records unreadable, and the fixed pin order is what guarantees it;
  * a ONE-BYTE change flips ``current`` to ``drifted``. This is the whole point:
    the field it replaces was prose, and prose said "389dfee + uncommitted working
    tree" while the tested bytes were in no commit at all;
  * a deleted file separates ``moved`` from ``gone``. A rename must not read as a
    deletion — the bytes under test survived, under another name, and a report
    that called that ``gone`` would send someone looking for a regression that
    never happened;
  * ``--write`` ROUND-TRIPS. It is run against a real record, so corrupting the
    surrounding text is the failure that costs evidence; replacing a block must
    leave every other byte identical, and a second run must be a no-op;
  * historical records are never touched: a record with no block reports an error
    instead of growing one, because a pin invented after the fact is a fabrication
    wearing a checksum.
"""
from __future__ import annotations

import io
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

EVALS_DIR = Path(__file__).resolve().parents[1]
if str(EVALS_DIR) not in sys.path:
    sys.path.insert(0, str(EVALS_DIR))

import record_pins as RP  # noqa: E402


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


RECORD = """\
# Eval result — demo-skill

| Field | Value |
|-------|-------|
| Skill | `demo-skill` |
| Run commit | `abcdef123456` + uncommitted working tree |
| Anchor commit | `none` |

## Per-canary results

| Canary id | rubric_pass (0/1) |
|-----------|-------------------|
| `demo-one` | 1 |

## Verdict

- **Regression:** PASS.
"""


class TreeTestCase(unittest.TestCase):
    """A temp tree standing in for a checkout, with one skill in it."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.make_skill()

    def make_skill(self, skill: str = "demo-skill", *, reference: bool = True) -> None:
        _write(self.root / "skills" / skill / "SKILL.md", "# skill\nstep one\n")
        _write(self.root / "skills" / skill / "LESSONS.md", "- a lesson\n")
        if reference:
            _write(self.root / "skills" / skill / "reference.md", "long detail\n")
        _write(self.root / "evals" / "canaries" / f"{skill}.yaml",
               f"skill: {skill}\ncanaries: []\n")


class EmitTests(TreeTestCase):
    def test_emit_is_deterministic(self) -> None:
        first, _ = RP.build_block(self.root, "demo-skill")
        second, _ = RP.build_block(self.root, "demo-skill")
        self.assertEqual(first.render(), second.render())

    def test_emit_order_is_fixed_not_filesystem_order(self) -> None:
        block, _ = RP.build_block(self.root, "demo-skill")
        self.assertEqual(
            [pin.path for pin in block.pins],
            [
                "skills/demo-skill/SKILL.md",
                "skills/demo-skill/LESSONS.md",
                "skills/demo-skill/reference.md",
                "evals/canaries/demo-skill.yaml",
            ],
        )

    def test_the_canary_set_is_pinned_too(self) -> None:
        """Editing a prompt changes a verdict as surely as editing the SKILL.md."""
        block, _ = RP.build_block(self.root, "demo-skill")
        self.assertIn("evals/canaries/demo-skill.yaml",
                      [pin.path for pin in block.pins])

    def test_additional_top_level_markdown_guides_are_pinned(self) -> None:
        """A progressive-disclosure retier must not disappear from provenance."""
        _write(
            self.root / "skills" / "demo-skill" / "dossier-guide.md",
            "# Routed detail\n",
        )

        block, missing = RP.build_block(self.root, "demo-skill")

        self.assertEqual(missing, [])
        self.assertEqual(
            [pin.path for pin in block.pins],
            [
                "skills/demo-skill/SKILL.md",
                "skills/demo-skill/LESSONS.md",
                "skills/demo-skill/reference.md",
                "skills/demo-skill/dossier-guide.md",
                "evals/canaries/demo-skill.yaml",
            ],
        )

    def test_digest_and_size_match_the_bytes(self) -> None:
        block, _ = RP.build_block(self.root, "demo-skill")
        pin = next(p for p in block.pins if p.path.endswith("SKILL.md"))
        data = (self.root / "skills" / "demo-skill" / "SKILL.md").read_bytes()
        self.assertEqual(pin.sha256, RP.digest_bytes(data))
        self.assertEqual(pin.size, len(data))
        self.assertEqual(len(pin.sha256), RP.DIGEST_HEX)

    def test_an_absent_optional_file_is_reported_not_swallowed(self) -> None:
        """A skill may ship without a reference.md; "3 of 4" must still be sayable."""
        self.make_skill("thin-skill", reference=False)
        block, missing = RP.build_block(self.root, "thin-skill")
        self.assertEqual(missing, ["skills/thin-skill/reference.md"])
        self.assertEqual(len(block.pins), 3)

    def test_an_unknown_skill_is_an_error_not_an_empty_block(self) -> None:
        with self.assertRaises(RP.PinError):
            RP.build_block(self.root, "no-such-skill")

    def test_emit_cli_prints_a_parseable_block(self) -> None:
        buf, err = io.StringIO(), io.StringIO()
        with redirect_stdout(buf), redirect_stderr(err):
            rc = RP.main(["--emit", "--skill", "demo-skill", "--repo", str(self.root)])
        self.assertEqual(rc, RP.EXIT_OK)
        parsed = RP.parse_block(buf.getvalue())
        self.assertEqual(parsed.skill, "demo-skill")
        self.assertEqual(len(parsed.pins), 4)

    def test_emit_without_a_skill_is_a_usage_error(self) -> None:
        with self.assertRaises(SystemExit), redirect_stderr(io.StringIO()):
            RP.main(["--emit", "--repo", str(self.root)])


class ParseTests(TreeTestCase):
    def test_block_round_trips_through_render_and_parse(self) -> None:
        block, _ = RP.build_block(self.root, "demo-skill")
        self.assertEqual(RP.parse_block(block.render()), block)

    def test_a_path_is_read_whole_even_with_spaces(self) -> None:
        """``path=`` is last on the line precisely so this cannot truncate."""
        text = "```eval-pin v1\nskill s\npin sha256=abcd bytes=1 path=a dir/x.md\n```\n"
        self.assertEqual(RP.parse_block(text).pins[0].path, "a dir/x.md")

    def test_no_block_parses_to_none(self) -> None:
        self.assertIsNone(RP.parse_block(RECORD))

    def test_an_unclosed_block_is_an_error(self) -> None:
        with self.assertRaises(RP.PinError):
            RP.parse_block("```eval-pin v1\nskill s\n")

    def test_a_future_version_is_refused_rather_than_misread(self) -> None:
        with self.assertRaises(RP.PinError):
            RP.parse_block("```eval-pin v9\nskill s\n```\n")

    def test_a_malformed_pin_line_names_its_line_number(self) -> None:
        text = RECORD + "\n```eval-pin v1\nskill s\npin sha256=abcd path=x.md\n```\n"
        with self.assertRaises(RP.PinError) as ctx:
            RP.parse_block(text)
        self.assertIn("expected `pin sha256=", str(ctx.exception))

    def test_skill_is_read_from_the_metadata_row_when_there_is_no_block(self) -> None:
        self.assertEqual(RP.skill_from_record(RECORD), "demo-skill")

    def test_an_unfilled_template_row_is_not_a_skill_named_angle_skill(self) -> None:
        self.assertIsNone(RP.skill_from_record("| Skill | `<skill>` |\n"))


class WriteTests(TreeTestCase):
    def _record(self, text: str = RECORD) -> Path:
        return _write(self.root / "evals" / "results" / "demo.md", text)

    def _run_write(self, record: Path, *extra: str) -> int:
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            return RP.main(["--write", str(record), "--repo", str(self.root), *extra])

    def test_write_inserts_a_block_and_preserves_every_other_line(self) -> None:
        record = self._record()
        before = record.read_text(encoding="utf-8").splitlines()
        self.assertEqual(self._run_write(record), RP.EXIT_OK)

        text = record.read_text(encoding="utf-8")
        self.assertEqual(RP.parse_block(text).skill, "demo-skill")

        # Delete the block back out and the record is byte-for-byte what it was,
        # give or take the single blank line the inserter puts in front of it.
        start, end = RP.find_block(text)
        after = text.splitlines()
        remainder = [ln for ln in after[:start] + after[end:] if ln.strip()]
        self.assertEqual(remainder, [ln for ln in before if ln.strip()])

    def test_write_places_the_block_after_the_metadata_table(self) -> None:
        record = self._record()
        self._run_write(record)
        lines = record.read_text(encoding="utf-8").splitlines()
        fence = next(i for i, ln in enumerate(lines) if ln.startswith("```eval-pin"))
        self.assertTrue(lines[fence - 2].startswith("| Anchor commit |"))
        self.assertLess(fence, lines.index("## Per-canary results"))

    def test_write_fills_the_shipped_templates_placeholder_block(self) -> None:
        """The main path: copy TEMPLATE.md, fill the Skill row, run --write.

        The template's block is all ``<16 hex>`` placeholders, which no parser can
        read as pins. Refusing to write over one would break the only workflow this
        tool has.
        """
        template = EVALS_DIR.parents[1] / "evals" / "results" / "TEMPLATE.md"
        if not template.is_file():
            self.skipTest(f"{template} is absent")
        text = template.read_text(encoding="utf-8").replace(
            "| Skill | `<skill>` |", "| Skill | `demo-skill` |")
        record = self._record(text)

        self.assertEqual(self._run_write(record), RP.EXIT_OK)
        block = RP.parse_block(record.read_text(encoding="utf-8"))
        self.assertEqual(block.skill, "demo-skill")
        self.assertEqual(len(block.pins), 4)
        self.assertNotIn("<16 hex>", record.read_text(encoding="utf-8"))

    def test_write_is_idempotent(self) -> None:
        record = self._record()
        self._run_write(record)
        once = record.read_text(encoding="utf-8")
        self._run_write(record)
        self.assertEqual(record.read_text(encoding="utf-8"), once)

    def test_refreshing_a_block_changes_only_the_block(self) -> None:
        record = self._record()
        self._run_write(record)
        before = record.read_text(encoding="utf-8")

        _write(self.root / "skills" / "demo-skill" / "SKILL.md", "# skill\nstep two\n")
        self._run_write(record)
        after = record.read_text(encoding="utf-8")

        self.assertNotEqual(before, after)
        span_before, span_after = RP.find_block(before), RP.find_block(after)
        b_lines, a_lines = before.splitlines(), after.splitlines()
        self.assertEqual(b_lines[:span_before[0]], a_lines[:span_after[0]])
        self.assertEqual(b_lines[span_before[1]:], a_lines[span_after[1]:])

    def test_write_keeps_the_trailing_newline(self) -> None:
        record = self._record()
        self._run_write(record)
        self.assertTrue(record.read_text(encoding="utf-8").endswith("\n"))

    def test_write_refuses_a_record_whose_skill_it_cannot_tell(self) -> None:
        record = _write(self.root / "evals" / "results" / "mystery.md", "# no table\n")
        buf = io.StringIO()
        with redirect_stdout(io.StringIO()), redirect_stderr(buf):
            rc = RP.main(["--write", str(record), "--repo", str(self.root)])
        self.assertEqual(rc, RP.EXIT_ERROR)
        self.assertIn("--skill", buf.getvalue())

    def test_explicit_skill_overrides_an_unreadable_record(self) -> None:
        record = _write(self.root / "evals" / "results" / "mystery.md", "# no table\n")
        self.assertEqual(
            self._run_write(record, "--skill", "demo-skill"), RP.EXIT_OK)
        self.assertEqual(
            RP.parse_block(record.read_text(encoding="utf-8")).skill, "demo-skill")

    def test_a_missing_record_is_an_error_not_a_new_file(self) -> None:
        record = self.root / "evals" / "results" / "absent.md"
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            rc = RP.main(["--write", str(record), "--repo", str(self.root),
                          "--skill", "demo-skill"])
        self.assertEqual(rc, RP.EXIT_ERROR)
        self.assertFalse(record.exists())


class RepoTestCase(TreeTestCase):
    """A throwaway git repository, so ``--report`` has a real revision to read."""

    def setUp(self) -> None:
        super().setUp()
        self.git("init", "-q")
        # ``git init -b`` is not portable back to the git this repo's own machines
        # run (2.39 does not have the switch); the symbolic-ref does the same job.
        self.git("symbolic-ref", "HEAD", "refs/heads/main")
        self.git("config", "user.email", "tests@example.invalid")
        self.git("config", "user.name", "tests")
        # A machine-wide core.hooksPath or commit.gpgsign would otherwise reach
        # into this throwaway repo; point both somewhere harmless rather than
        # reaching for --no-verify, which this repo's contract forbids.
        self.git("config", "core.hooksPath", str(self.root / ".no-hooks"))
        self.git("config", "commit.gpgsign", "false")
        self.commit("initial")

    def git(self, *args: str) -> subprocess.CompletedProcess:
        proc = subprocess.run(["git", *args], cwd=str(self.root),
                              capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return proc

    def commit(self, message: str) -> None:
        # ``-A`` inside a tempfile repository the test just built — never this
        # checkout, where the contract is explicit-paths-only.
        self.git("add", "-A")
        self.git("commit", "-q", "-m", message)

    def statuses(self, block: RP.PinBlock, rev: str = "HEAD") -> dict[str, str]:
        resolved = RP._resolve_rev(self.root, rev)
        return {row["pin"].path: row["status"]
                for row in RP.report(self.root, block, resolved)}


class ReportTests(RepoTestCase):
    def test_an_unchanged_tree_is_all_current(self) -> None:
        block, _ = RP.build_block(self.root, "demo-skill")
        self.assertEqual(set(self.statuses(block).values()), {"current"})

    def test_one_byte_flips_current_to_drifted(self) -> None:
        block, _ = RP.build_block(self.root, "demo-skill")
        skill_md = self.root / "skills" / "demo-skill" / "SKILL.md"
        skill_md.write_bytes(skill_md.read_bytes().replace(b"one", b"two"))
        self.commit("one byte")

        statuses = self.statuses(block)
        self.assertEqual(statuses["skills/demo-skill/SKILL.md"], "drifted")
        self.assertEqual(statuses["skills/demo-skill/LESSONS.md"], "current")

    def test_a_trailing_newline_is_a_drift(self) -> None:
        """Whitespace is bytes. A pin that ignored it would be a weaker claim."""
        block, _ = RP.build_block(self.root, "demo-skill")
        lessons = self.root / "skills" / "demo-skill" / "LESSONS.md"
        lessons.write_bytes(lessons.read_bytes() + b"\n")
        self.commit("newline")
        self.assertEqual(self.statuses(block)["skills/demo-skill/LESSONS.md"],
                         "drifted")

    def test_a_deleted_file_is_gone(self) -> None:
        block, _ = RP.build_block(self.root, "demo-skill")
        (self.root / "skills" / "demo-skill" / "reference.md").unlink()
        self.commit("drop the reference tier")
        self.assertEqual(self.statuses(block)["skills/demo-skill/reference.md"],
                         "gone")

    def test_a_renamed_skill_is_moved_not_gone(self) -> None:
        """The bytes under test survived; calling that "gone" sends someone hunting."""
        block, _ = RP.build_block(self.root, "demo-skill")
        self.git("mv", "skills/demo-skill", "skills/renamed-skill")
        self.git("mv", "evals/canaries/demo-skill.yaml",
                 "evals/canaries/renamed-skill.yaml")
        self.commit("rename the skill")

        self.assertEqual(set(self.statuses(block).values()), {"moved"})

    def test_moved_names_the_new_path(self) -> None:
        block, _ = RP.build_block(self.root, "demo-skill")
        self.git("mv", "-f", "skills/demo-skill/reference.md",
                 "skills/demo-skill/LESSONS.md")
        self.commit("fold the reference tier into LESSONS")

        resolved = RP._resolve_rev(self.root, "HEAD")
        rows = {r["pin"].path: r for r in RP.report(self.root, block, resolved)}
        row = rows["skills/demo-skill/reference.md"]
        self.assertEqual(row["status"], "moved")
        self.assertIn("skills/demo-skill/LESSONS.md", row["note"])

    def test_content_outside_the_instruction_shapes_is_not_a_move(self) -> None:
        """A copy into docs/ is not a rename of an instruction file; bounded search."""
        block, _ = RP.build_block(self.root, "demo-skill")
        text = (self.root / "skills" / "demo-skill" / "reference.md").read_bytes()
        (self.root / "skills" / "demo-skill" / "reference.md").unlink()
        _write(self.root / "docs" / "reference.md", text.decode())
        self.commit("move the reference out of the skill")
        self.assertEqual(self.statuses(block)["skills/demo-skill/reference.md"],
                         "gone")

    def test_report_reads_an_older_revision(self) -> None:
        block, _ = RP.build_block(self.root, "demo-skill")
        first = self.git("rev-parse", "HEAD").stdout.strip()
        skill_md = self.root / "skills" / "demo-skill" / "SKILL.md"
        skill_md.write_bytes(b"rewritten\n")
        self.commit("rewrite")

        self.assertEqual(self.statuses(block, "HEAD")["skills/demo-skill/SKILL.md"],
                         "drifted")
        self.assertEqual(self.statuses(block, first)["skills/demo-skill/SKILL.md"],
                         "current")

    def test_report_cli_exits_zero_on_drift(self) -> None:
        """Report-only by design: no new gate while the process-weight decision is open."""
        record = _write(self.root / "evals" / "results" / "demo.md", RECORD)
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            RP.main(["--write", str(record), "--repo", str(self.root)])
        skill_md = self.root / "skills" / "demo-skill" / "SKILL.md"
        skill_md.write_bytes(b"rewritten\n")
        self.commit("rewrite")

        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = RP.main(["--report", str(record), "--repo", str(self.root)])
        self.assertEqual(rc, RP.EXIT_OK)
        self.assertIn("drifted", buf.getvalue())

    def test_report_refuses_a_record_with_no_block(self) -> None:
        """Historical records have none, and this tool never invents one."""
        record = _write(self.root / "evals" / "results" / "old.md", RECORD)
        buf = io.StringIO()
        with redirect_stdout(io.StringIO()), redirect_stderr(buf):
            rc = RP.main(["--report", str(record), "--repo", str(self.root)])
        self.assertEqual(rc, RP.EXIT_ERROR)
        self.assertIn("no eval-pin block", buf.getvalue())

    def test_an_unresolvable_revision_is_an_error(self) -> None:
        record = _write(self.root / "evals" / "results" / "demo.md", RECORD)
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            RP.main(["--write", str(record), "--repo", str(self.root)])
        buf = io.StringIO()
        with redirect_stdout(io.StringIO()), redirect_stderr(buf):
            rc = RP.main(["--report", str(record), "--repo", str(self.root),
                          "--rev", "no-such-ref"])
        self.assertEqual(rc, RP.EXIT_ERROR)
        self.assertIn("cannot resolve revision", buf.getvalue())


class ShippedTemplateTests(unittest.TestCase):
    """The template is the only place a new record's shape comes from."""

    def setUp(self) -> None:
        self.template = EVALS_DIR.parents[1] / "evals" / "results" / "TEMPLATE.md"
        if not self.template.is_file():          # published export ships it; be safe
            self.skipTest(f"{self.template} is absent")
        self.text = self.template.read_text(encoding="utf-8")

    def test_the_template_carries_a_block_this_tool_can_find(self) -> None:
        self.assertIsNotNone(RP.find_block(self.text))

    def test_the_old_free_form_git_sha_row_is_gone(self) -> None:
        self.assertNotIn("| Git SHA |", self.text)

    def test_both_commit_rows_are_present(self) -> None:
        self.assertIn("| Run commit |", self.text)
        self.assertIn("| Anchor commit |", self.text)

    def test_anchor_commit_offers_none_as_an_honest_answer(self) -> None:
        anchor = next(ln for ln in self.text.splitlines()
                      if ln.startswith("| Anchor commit |"))
        self.assertIn("`none`", anchor)


if __name__ == "__main__":
    unittest.main()
