"""Tests for the instruction-file budget gate.

Run with (from the repo root):
    .venv/bin/python -m unittest discover -s automation/metrics/tests

Every test builds a throwaway tree and measures that, so nothing here reads the
real repo (or the private overlay).

What is pinned here:
  * discovery used to be a fixed glob list — the repo-root ``AGENTS.md`` plus
    ``skills/*/AGENTS.md``. A folder leaf such as ``docs/designs/AGENTS.md``,
    which auto-loads for any agent reading in that folder, was never measured
    while the module docstring claimed it measured every ``AGENTS.md``;
  * a leaf carries its own, much tighter tier (100 lines AND 4 KiB) — being
    under the root's 500-line budget must not make an over-weight leaf pass;
  * the walk must not descend into the private overlay, scratch trees, or
    dot-directories, and must not follow a symlink back into the tree (which
    would report the same file twice);
  * a file inside the NEAR band is warned about and is NOT a violation — the
    band exists because the budget is a cliff and the report used to say nothing
    until you were already over it.
"""
from __future__ import annotations

import io
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

METRICS_DIR = Path(__file__).resolve().parents[1]
if str(METRICS_DIR) not in sys.path:
    sys.path.insert(0, str(METRICS_DIR))

import instruction_budget as IB  # noqa: E402


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


class BudgetTestCase(unittest.TestCase):
    """Base: a temp tree standing in for the repo root."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        # build_report() also consults the overlay and the generated store
        # README, both of which live outside the temp tree. Silence them so a
        # maintainer checkout with an overlay mounted measures the same set as
        # CI, which has neither.
        for name, result in (("_private_skills_dir", None), ("_store_readme_target", ())):
            patcher = mock.patch.object(IB, name, lambda r=result: r)
            patcher.start()
            self.addCleanup(patcher.stop)

    def kinds(self) -> dict[str, str]:
        """Map each discovered AGENTS.md's relative path -> its kind."""
        return {
            path.relative_to(self.root).as_posix(): kind
            for kind, path in IB._agents_targets(self.root)
        }


class DiscoveryTests(BudgetTestCase):
    def test_root_and_leaf_are_separate_tiers(self) -> None:
        _write(self.root / "AGENTS.md", "root\n")
        _write(self.root / "docs" / "designs" / "AGENTS.md", "leaf\n")
        _write(self.root / "skills" / "job-search" / "AGENTS.md", "skill leaf\n")

        self.assertEqual(
            self.kinds(),
            {
                "AGENTS.md": "AGENTS.md",
                "docs/designs/AGENTS.md": "AGENTS.md (leaf)",
                "skills/job-search/AGENTS.md": "AGENTS.md (leaf)",
            },
        )

    def test_walk_skips_overlay_scratch_and_dot_dirs(self) -> None:
        _write(self.root / "AGENTS.md", "root\n")
        for hidden in ("private", "local", ".venv", "node_modules", ".claude"):
            _write(self.root / hidden / "AGENTS.md", "not ours\n")
        _write(self.root / "private" / "skills" / "x" / "AGENTS.md", "not ours\n")

        self.assertEqual(self.kinds(), {"AGENTS.md": "AGENTS.md"})

    def test_symlinked_directory_does_not_double_count(self) -> None:
        _write(self.root / "AGENTS.md", "root\n")
        _write(self.root / "docs" / "AGENTS.md", "leaf\n")
        (self.root / "mirror").symlink_to(self.root / "docs", target_is_directory=True)

        self.assertEqual(
            self.kinds(),
            {"AGENTS.md": "AGENTS.md", "docs/AGENTS.md": "AGENTS.md (leaf)"},
        )

    def test_skill_targets_do_not_repeat_the_walk(self) -> None:
        """The public skills/ dir is walked, so globbing it again would duplicate."""
        _write(self.root / "skills" / "job-search" / "AGENTS.md", "leaf\n")
        _write(self.root / "skills" / "job-search" / "SKILL.md", "skill\n")

        found = [
            (kind, path.relative_to(self.root).as_posix())
            for kind, path in IB._iter_targets(self.root)
        ]
        self.assertEqual(
            found.count(("AGENTS.md (leaf)", "skills/job-search/AGENTS.md")), 1
        )
        self.assertIn(("SKILL.md", "skills/job-search/SKILL.md"), found)


class LeafBudgetTests(BudgetTestCase):
    def _violations(self):
        _rows, violations = IB.build_report(self.root)
        return {v["path"]: v for v in violations}

    def test_leaf_within_both_dimensions_passes(self) -> None:
        _write(self.root / "docs" / "AGENTS.md", "- a pointer\n" * 20)
        self.assertEqual(self._violations(), {})

    def test_leaf_over_the_line_budget_fails(self) -> None:
        _write(self.root / "docs" / "AGENTS.md", "line\n" * 101)
        violation = self._violations()["docs/AGENTS.md"]
        self.assertTrue(violation["over_primary"])
        self.assertEqual(violation["budget"], 100)

    def test_leaf_under_the_line_budget_can_still_fail_on_bytes(self) -> None:
        """100 lines of dense prose is past 4 KiB; the line count alone misses it."""
        _write(self.root / "docs" / "AGENTS.md", ("x" * 90 + "\n") * 60)
        violation = self._violations()["docs/AGENTS.md"]
        self.assertFalse(violation["over_primary"])
        self.assertTrue(violation["over_bytes"])
        self.assertEqual(violation["byte_budget"], 4096)

    def test_root_keeps_the_root_budget(self) -> None:
        _write(self.root / "AGENTS.md", "line\n" * 300)
        self.assertEqual(self._violations(), {})


class NearBudgetTests(BudgetTestCase):
    """NEAR warns before the cliff and never fails, in --strict or out of it."""

    def _rows(self) -> dict[str, dict]:
        rows, _violations = IB.build_report(self.root)
        return {r["path"]: r for r in rows}

    def test_a_file_inside_the_near_band_is_flagged_but_not_a_violation(self) -> None:
        near = int(IB.BUDGETS["SKILL.md"] * IB.NEAR_BUDGET_FRACTION) + 1
        _write(self.root / "skills" / "x" / "SKILL.md", "line\n" * near)
        row = self._rows()["skills/x/SKILL.md"]
        self.assertTrue(row["near"])
        self.assertFalse(row["over"])
        _rows, violations = IB.build_report(self.root)
        self.assertEqual(violations, [])

    def test_comfortably_under_budget_is_not_near(self) -> None:
        _write(self.root / "skills" / "x" / "SKILL.md", "line\n" * 100)
        self.assertFalse(self._rows()["skills/x/SKILL.md"]["near"])

    def test_over_budget_is_over_not_near(self) -> None:
        """The two are exclusive, so a file cannot be reported twice."""
        _write(self.root / "skills" / "x" / "SKILL.md",
               "line\n" * (IB.BUDGETS["SKILL.md"] + 1))
        row = self._rows()["skills/x/SKILL.md"]
        self.assertTrue(row["over"])
        self.assertFalse(row["near"])

    def test_a_leaf_can_be_near_on_bytes_alone(self) -> None:
        """The byte budget is a real dimension, so it needs its own warning band."""
        target = int(IB.BYTE_BUDGETS["AGENTS.md (leaf)"] * IB.NEAR_BUDGET_FRACTION) + 1
        line = "x" * 79 + "\n"                       # 80 bytes, well under 100 lines
        _write(self.root / "docs" / "AGENTS.md", line * (target // 80 + 1))
        row = self._rows()["docs/AGENTS.md"]
        self.assertTrue(row["near"])
        self.assertFalse(row["over"])

    def test_strict_still_exits_zero_with_a_near_file(self) -> None:
        """The whole point: this is a heads-up, not a gate."""
        near = int(IB.BUDGETS["SKILL.md"] * IB.NEAR_BUDGET_FRACTION) + 1
        _write(self.root / "skills" / "x" / "SKILL.md", "line\n" * near)
        with mock.patch.object(IB, "REPO_ROOT", self.root):
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = IB.main(["--strict"])
        self.assertEqual(rc, 0)
        out = buf.getvalue()
        self.assertIn("NEAR", out)
        self.assertIn(f"({IB.BUDGETS['SKILL.md'] - near} left)", out)
        self.assertIn("OK: all instruction files within budget.", out)


if __name__ == "__main__":
    unittest.main()
