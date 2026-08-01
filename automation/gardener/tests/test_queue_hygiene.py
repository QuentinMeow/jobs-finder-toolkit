"""Tests for the queue-hygiene gardener routine.

Run with (from the repo root):
    .venv/bin/python -m unittest discover \
        -s automation/gardener/tests \
        -t automation/gardener/tests

Three properties carry this routine, and each has its own class below.

1. **It never gates.** Age is a prompt for judgement, not a violated invariant;
   the whole reason this lives in the gardener rather than the reconciler is that
   a blocking age flag fails every unrelated commit until somebody grooms a
   backlog. So: exit 0 with findings, exit 0 without, exit 0 on a malformed item.
2. **It no-ops on a tree with no queues.** The published export ships neither
   `message-queue/` nor `tasks/`, so "the folders are absent" is the shape most
   installs are in — a real code path, not a hypothetical.
3. **It never names a private item.** The private half prints counts only. A
   filename in `private/message-queue/` is a kebab slug of the owner's real
   pipeline, and this report is written to be pasted into a PR description.

Every test runs against a throwaway tree (``C.REPO_ROOT`` is redirected), never the
real repo and never the overlay — ``test_fixture_isolation.py`` is the standing guard
for the folder.
"""
from __future__ import annotations

import datetime
import io
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

GARDENER_DIR = Path(__file__).resolve().parents[1]
if str(GARDENER_DIR) not in sys.path:
    sys.path.insert(0, str(GARDENER_DIR))

import queue_hygiene as QH  # noqa: E402

TODAY = datetime.date(2026, 7, 31)


def _days_ago(n: int) -> str:
    return (TODAY - datetime.timedelta(days=n)).isoformat()


class TempTree(unittest.TestCase):
    """A throwaway repo root with the queue/task folders built on demand."""

    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="queue-hygiene-")).resolve()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        saved = QH.C.REPO_ROOT
        QH.C.REPO_ROOT = self.root
        self.addCleanup(lambda: setattr(QH.C, "REPO_ROOT", saved))

    # ── fixture builders ──────────────────────────────────────────────────
    def review(self, name: str, filed: str, root: Path | None = None) -> None:
        self._write(root, f"message-queue/needs-human/reviews/{name}", (
            f"# A thing to look at\n\n- **Filed**: {filed}\n"
            "- **Look at**: somewhere\n- **Why you might care**: reasons\n"
            "- **If you do nothing**: nothing happens\n"))

    def decision(self, name: str, filed: str, status: str = "awaiting-owner-input",
                 revisit: str | None = None, root: Path | None = None) -> None:
        body = (f"# A question\n\n- **Status**: {status}\n- **Filed**: {filed}\n"
                "- **Blocking**: nothing\n- **Default path**: carry on\n")
        if revisit is not None:
            body += f"- **Revisit when**: {revisit}\n"
        body += "\n**Your answer:** ______\n"
        self._write(root, f"message-queue/needs-human/decisions/{name}", body)

    def task(self, task_id: str, status: str, worklog: str | None = None,
             root: Path | None = None) -> None:
        base = f"tasks/{status}/{task_id}"
        self._write(root, f"{base}/task.md",
                    "# A task\n\n- **Priority**: P2\n- **Area**: harness\n"
                    "- **Source**: nowhere\n")
        if worklog:
            self._write(root, f"{base}/worklog.md",
                        f"# Worklog — {task_id}\n\n## {worklog} — session 1 (agent)\n\n- did a thing\n")

    def stage_plan(self, slug: str, body: str, root: Path | None = None) -> None:
        self._write(root, f"docs/designs/{slug}/execution-plan.md", body)

    def _write(self, root: Path | None, rel: str, body: str) -> None:
        path = (root or self.root) / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")

    # ── drivers ───────────────────────────────────────────────────────────
    def scan(self, root: Path | None = None) -> dict:
        target = root or self.root
        return QH.scan(target, TODAY, [target / "docs" / "designs"])

    def report(self) -> str:
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = QH.run()
        self.assertEqual(rc, 0, "the routine must never fail a caller")
        return buf.getvalue()


class TestAbsentTrees(TempTree):
    """Property 2 — the exported public tree ships neither folder."""

    def test_no_queue_and_no_tasks_is_not_an_error(self) -> None:
        self.assertFalse((self.root / "message-queue").exists())
        self.assertFalse((self.root / "tasks").exists())
        res = self.scan()
        self.assertFalse(res["present"])
        out = self.report()
        self.assertIn("nothing to check", out)
        self.assertNotIn("reviews/", out)

    def test_absent_tree_still_exits_zero(self) -> None:
        buf = io.StringIO()
        with redirect_stdout(buf):
            self.assertEqual(QH.run(), 0)

    def test_tasks_without_a_message_queue(self) -> None:
        """Half-adopted process folders must not crash the other half."""
        self.task("2026-01-01-old-one", "1_in-progress")
        res = self.scan()
        self.assertTrue(res["present"])
        self.assertFalse(res["queue_present"])
        self.assertEqual(len(res["tasks"]), 1)
        out = self.report()
        self.assertIn("2026-01-01-old-one", out)
        self.assertNotIn("reviews/", out)

    def test_message_queue_without_tasks(self) -> None:
        self.review("old.md", _days_ago(90))
        res = self.scan()
        self.assertTrue(res["queue_present"])
        self.assertFalse(res["tasks_present"])
        out = self.report()
        self.assertIn("old.md", out)
        self.assertNotIn("dwelling", out)

    def test_empty_but_present_folders_report_zero_counts(self) -> None:
        (self.root / "message-queue/needs-human/reviews").mkdir(parents=True)
        (self.root / "tasks/1_in-progress").mkdir(parents=True)
        out = self.report()
        self.assertIn("none past 30 days (0 item(s))", out)
        self.assertIn("nothing aging past its threshold", out)


class TestReviewAge(TempTree):
    """Dimension 1 — reviews/ items past the 30-day sweep in AGENTS.md."""

    def test_an_old_review_is_reported(self) -> None:
        self.review("stale-look.md", _days_ago(45))
        res = self.scan()
        self.assertEqual([r["name"] for r in res["reviews"]], ["stale-look.md"])
        self.assertEqual(res["reviews"][0]["age"], 45)
        self.assertIn("stale-look.md", self.report())

    def test_the_boundary_is_the_declared_limit(self) -> None:
        self.review("edge.md", _days_ago(QH.REVIEW_MAX_AGE_DAYS))
        self.assertEqual(self.scan()["reviews"], [], "exactly at the limit is not yet old")
        self.review("edge.md", _days_ago(QH.REVIEW_MAX_AGE_DAYS + 1))
        self.assertEqual(len(self.scan()["reviews"]), 1)

    def test_a_readme_is_not_an_item(self) -> None:
        self._write(None, "message-queue/needs-human/reviews/README.md",
                    "# reviews/\n\n- **Filed**: 2020-01-01\n")
        self.assertEqual(self.scan()["reviews_total"], 0)


class TestDecisionAge(TempTree):
    """Dimension 3 — decisions/ pending longer than the declared window."""

    def test_a_long_pending_decision_is_reported(self) -> None:
        self.decision("slow.md", _days_ago(40))
        res = self.scan()
        self.assertEqual([d["name"] for d in res["decisions"]], ["slow.md"])
        self.assertIn("slow.md", self.report())

    def test_the_boundary_is_the_declared_limit(self) -> None:
        self.decision("edge.md", _days_ago(QH.DECISION_MAX_AGE_DAYS))
        self.assertEqual(self.scan()["decisions"], [])
        self.decision("edge.md", _days_ago(QH.DECISION_MAX_AGE_DAYS + 1))
        self.assertEqual(len(self.scan()["decisions"]), 1)

    def test_trailing_prose_after_the_filed_date_is_tolerated(self) -> None:
        """Real items write ``- **Filed**: 2026-07-31 (public surface for ...)``."""
        self.decision("prosey.md", f"{_days_ago(40)} (first raised in the overlay)")
        self.assertEqual(len(self.scan()["decisions"]), 1)

    def test_a_parked_item_is_not_reported_for_age(self) -> None:
        """Parked means deferred ON PURPOSE — its age is not the finding."""
        self.decision("parked.md", _days_ago(200), status="parked-until-revisit (2026-01-01)")
        res = self.scan()
        self.assertEqual(res["decisions"], [])
        self.assertEqual(res["parked_total"], 1)

    def test_a_decision_with_no_date_is_flagged_as_undated_not_crashed(self) -> None:
        self._write(None, "message-queue/needs-human/decisions/nodate.md",
                    "# Q\n\n- **Status**: awaiting-owner-input\n\n**Your answer:** ______\n")
        res = self.scan()
        self.assertEqual([u["name"] for u in res["undated"]], ["nodate.md"])
        self.assertIn("no parseable date", self.report())


class TestParkedRevisitCondition(TempTree):
    """Dimension 4 — a parked item whose revisit condition already shipped."""

    SHIPPED_PLAN = (
        "# Execution plan — raw data layer\n\n"
        "## Stage 2 — builder — SHIPPED (PR #51)\n\nbody\n\n"
        "## Stage 3 — pipeline integration — SHIPPED (PR #52)\n\nbody\n\n"
        "## Stage 5 — email track — PLANNED\n\nbody\n")

    def test_a_shipped_stage_reopens_a_parked_item(self) -> None:
        self.stage_plan("raw-data-layer", self.SHIPPED_PLAN)
        self.decision("logs.md", _days_ago(10), status="parked-until-revisit",
                      revisit="raw-data-layer execution-plan stage 3 (pipeline\n  integration) has shipped")
        res = self.scan()
        self.assertEqual(len(res["parked"]), 1)
        self.assertEqual((res["parked"][0]["design"], res["parked"][0]["stage"]),
                         ("raw-data-layer", "3"))
        self.assertIn("SHIPPED", self.report())

    def test_a_wrapped_revisit_line_is_read_whole(self) -> None:
        """The stage number lives on the continuation line in the real item."""
        self.stage_plan("raw-data-layer", self.SHIPPED_PLAN)
        self.decision("wrapped.md", _days_ago(10), status="parked-until-revisit",
                      revisit="raw-data-layer execution-plan\n  stage 3 has shipped")
        self.assertEqual(len(self.scan()["parked"]), 1)

    def test_an_unshipped_stage_stays_parked(self) -> None:
        self.stage_plan("raw-data-layer", self.SHIPPED_PLAN)
        self.decision("later.md", _days_ago(10), status="parked-until-revisit",
                      revisit="raw-data-layer execution-plan stage 5 has shipped")
        res = self.scan()
        self.assertEqual(res["parked"], [])
        self.assertEqual(res["parked_total"], 1)
        self.assertIn("none whose revisit condition names a shipped stage", self.report())

    def test_a_stage_in_another_design_does_not_match(self) -> None:
        self.stage_plan("raw-data-layer", self.SHIPPED_PLAN)
        self.decision("other.md", _days_ago(10), status="parked-until-revisit",
                      revisit="token-usage-modes execution-plan stage 3 has shipped")
        self.assertEqual(self.scan()["parked"], [])

    def test_a_revisit_condition_with_no_stage_is_not_guessed_at(self) -> None:
        self.stage_plan("raw-data-layer", self.SHIPPED_PLAN)
        self.decision("vague.md", _days_ago(10), status="parked-until-revisit",
                      revisit="when the owner has run a full search cycle")
        self.assertEqual(self.scan()["parked"], [])

    def test_shipped_stages_reads_the_heading_marker(self) -> None:
        self.stage_plan("raw-data-layer", self.SHIPPED_PLAN)
        self.assertEqual(QH.shipped_stages([self.root / "docs" / "designs"]),
                         {"raw-data-layer": {"2", "3"}})


class TestTaskDwell(TempTree):
    """Dimension 2 — tasks sitting in 1_in-progress / 3_in-review."""

    def test_a_long_dwelling_task_is_reported(self) -> None:
        self.task("2026-05-01-forgotten", "1_in-progress")
        res = self.scan()
        self.assertEqual([t["id"] for t in res["tasks"]], ["2026-05-01-forgotten"])
        self.assertEqual(res["tasks"][0]["source"], "filed")
        self.assertIn("filed (upper bound)", self.report())

    def test_both_dwell_statuses_are_covered(self) -> None:
        self.task("2026-05-01-a", "1_in-progress")
        self.task("2026-05-02-b", "3_in-review")
        self.assertEqual({t["status"] for t in self.scan()["tasks"]},
                         {"1_in-progress", "3_in-review"})

    def test_backlog_blocked_and_done_are_not_dwell(self) -> None:
        for status in ("0_backlog", "2_blocked", "4_done"):
            self.task(f"2020-01-01-{status}", status)
        res = self.scan()
        self.assertEqual(res["tasks"], [])
        self.assertEqual(res["tasks_total"], 0)

    def test_a_recent_worklog_entry_beats_the_filed_date(self) -> None:
        """A task filed months ago but worked yesterday is not stalled."""
        self.task("2026-01-01-still-moving", "3_in-review", worklog=_days_ago(2))
        res = self.scan()
        self.assertEqual(res["tasks"], [])
        self.assertEqual(res["tasks_total"], 1)

    def test_an_old_worklog_entry_is_the_reported_age(self) -> None:
        self.task("2026-01-01-stalled", "1_in-progress", worklog=_days_ago(60))
        res = self.scan()
        self.assertEqual(res["tasks"][0]["source"], "worklog")
        self.assertEqual(res["tasks"][0]["age"], 60)
        self.assertIn("last worklog entry", self.report())

    def test_the_boundary_is_the_declared_limit(self) -> None:
        self.task("2026-01-01-edge", "1_in-progress",
                  worklog=_days_ago(QH.TASK_MAX_DWELL_DAYS))
        self.assertEqual(self.scan()["tasks"], [])
        self.task("2026-01-01-edge", "1_in-progress",
                  worklog=_days_ago(QH.TASK_MAX_DWELL_DAYS + 1))
        self.assertEqual(len(self.scan()["tasks"]), 1)

    def test_a_misnamed_folder_is_left_to_the_reconciler(self) -> None:
        """``task-structure`` already fails the commit for this; no double report."""
        self.task("not-a-task-id", "1_in-progress")
        res = self.scan()
        self.assertEqual(res["tasks"], [])
        self.assertEqual(res["undated"], [])


class TestPrivateMirrorPrintsCountsOnly(TempTree):
    """Property 3 — the private half must be safe to paste verbatim."""

    def _mirror(self) -> Path:
        return self.root / QH.PRIVATE_MIRROR

    def test_no_private_item_name_reaches_the_report(self) -> None:
        mirror = self._mirror()
        self.review("acme-onsite-scheduling.md", _days_ago(90), root=mirror)
        self.decision("northwind-comp-band.md", _days_ago(90), root=mirror)
        self.task("2026-01-01-initech-recruiter-thread", "1_in-progress", root=mirror)
        out = self.report()
        for secret in ("acme-onsite-scheduling", "northwind-comp-band",
                       "initech-recruiter-thread"):
            self.assertNotIn(secret, out,
                             "a private item name reached a report written to be pasted")

    def test_the_counts_are_still_reported(self) -> None:
        mirror = self._mirror()
        self.review("a.md", _days_ago(90), root=mirror)
        self.review("b.md", _days_ago(1), root=mirror)
        self.decision("c.md", _days_ago(90), root=mirror)
        out = self.report()
        self.assertIn("reviews/ past 30d: 1 of 2", out)
        self.assertIn("decisions/ pending past 21d: 1 of 1", out)
        self.assertIn("will not name them", out)

    def test_an_unmounted_overlay_says_so(self) -> None:
        self.assertFalse(self._mirror().exists())
        self.assertNotIn("mirror", self.report())

    def test_a_mounted_but_empty_overlay_is_not_an_error(self) -> None:
        self._mirror().mkdir(parents=True)
        self.assertIn("not mounted — nothing to check", self.report())

    def test_the_public_half_still_names_its_items(self) -> None:
        """The counts-only rule is scoped to the mirror, not the whole report."""
        self.review("public-item.md", _days_ago(90))
        self.review("private-item.md", _days_ago(90), root=self._mirror())
        out = self.report()
        self.assertIn("public-item.md", out)
        self.assertNotIn("private-item.md", out)


class TestNeverGates(TempTree):
    """Property 1 — exit 0, always."""

    def test_exit_zero_with_findings_in_every_dimension(self) -> None:
        self.stage_plan("raw-data-layer",
                        "## Stage 3 — pipeline integration — SHIPPED (PR #52)\n")
        self.review("old.md", _days_ago(90))
        self.decision("slow.md", _days_ago(90))
        self.decision("parked.md", _days_ago(90), status="parked-until-revisit",
                      revisit="raw-data-layer stage 3 has shipped")
        self.task("2026-01-01-stalled", "3_in-review")
        buf = io.StringIO()
        with redirect_stdout(buf):
            self.assertEqual(QH.run(), 0)
        out = buf.getvalue()
        for expected in ("old.md", "slow.md", "parked.md", "2026-01-01-stalled"):
            self.assertIn(expected, out)

    def test_exit_zero_on_an_item_that_is_not_valid_utf8(self) -> None:
        """A corrupt byte in one item must not take the whole sweep down."""
        item = self.root / "message-queue/needs-human/decisions/binary.md"
        item.parent.mkdir(parents=True, exist_ok=True)
        item.write_bytes(b"# Q\n\n- **Filed**: \xff\xfe not a date\n")
        self.review("readable.md", _days_ago(90))
        buf = io.StringIO()
        with redirect_stdout(buf):
            self.assertEqual(QH.run(), 0)
        self.assertIn("readable.md", buf.getvalue(), "the sweep kept going")


class TestRegistration(unittest.TestCase):
    """A routine nobody can invoke is a file, not a routine."""

    def test_the_front_end_lists_it_and_runs_it_dry(self) -> None:
        import gardener  # noqa: PLC0415  (front-end imported only for this assertion)
        self.assertIn("queue-hygiene", gardener.ROUTINES)
        self.assertIn("queue-hygiene", gardener.ALL_ORDER)
        _, supports_apply = gardener.ROUTINES["queue-hygiene"]
        self.assertFalse(supports_apply, "report-only: --apply must be a no-op")
        self.assertEqual(gardener.ALL_ORDER[-1], "verify-links",
                         "verify-links stays last so its exit code is the --all gate")

    def test_the_dwell_statuses_are_the_reconcilers_statuses(self) -> None:
        """One definition of what a status folder is, shared with the gate."""
        self.assertTrue(set(QH.DWELL_STATUSES) <= set(QH.reconcile.STATUS_DIRS))


if __name__ == "__main__":
    unittest.main()
