"""Tests for the phase-summary time-accounting model (reader half).

Run with (from the repo root):
    .venv/bin/python -m unittest discover -s automation/metrics/tests

Every test builds a synthetic event log in a throwaway tree, so nothing here
reads a real session, the real ``logs/`` directory, or the private overlay. The
personal-token source is patched out for the same reason.

What is pinned here — these are the honesty properties, not conveniences:
  * the PARTITION invariant. ``active + local_subprocess + external_wait +
    approval_wait + unattributed`` equals the reference total exactly. ``active``
    is the residual, so double-counted time shows up as a NEGATIVE, which is
    clamped to 0 AND flagged, never published as a negative;
  * coverage always names its DENOMINATOR. Against the recorder's own span,
    contiguous phases make coverage 100% by construction, so a percentage
    without ``reference_source`` beside it is meaningless;
  * a long silence inside a phase is UNATTRIBUTED, not active. Six quiet minutes
    are not evidence of six minutes of reasoning, and the failure mode to guard
    against is a later "improvement" that reclassifies them to make coverage
    look better;
  * approval wait is DECLARED, never inferred: no marks means 0.0 s meaning
    "not measured", and an unpaired mark contributes 0 and is counted;
  * redaction is STRUCTURAL. A session whose label, cwd, command line and phase
    name all carry a poison token produces a summary containing none of it —
    and the same token IS present in the raw log, which is what proves the test
    is live rather than vacuous.
"""
from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

METRICS_DIR = Path(__file__).resolve().parents[1]
if str(METRICS_DIR) not in sys.path:
    sys.path.insert(0, str(METRICS_DIR))

import phase_recorder as PR  # noqa: E402
import phase_summary as PS  # noqa: E402

EPOCH = 1_700_000_000


class SessionLog:
    """Builds a synthetic ``<session>.jsonl`` with exact, chosen timings."""

    def __init__(self, path: Path, session: str = "phase-test"):
        self.path = path
        self.session = session
        self.seq = 0
        self.rows: list[dict] = []
        self.phase = None
        self.raw_lines: list[str] = []

    def add(self, event: str, mono: float, **fields) -> dict:
        epoch = fields.pop("mono_epoch", EPOCH)
        wall = epoch + mono
        row = {
            "v": 1,
            "session": self.session,
            "session_digest": PR.digest(self.session),
            "seq": self.seq,
            "ts": datetime.fromtimestamp(wall, timezone.utc).isoformat(),
            "mono": mono,
            "mono_epoch": epoch,
            "event": event,
            "phase": self.phase,
        }
        row.update(fields)
        self.seq += 1
        self.rows.append(row)
        return row

    # -- convenience wrappers mirroring the recorder's own subcommands ----
    def start(self, mono=0.0, **fields):
        return self.add("session_start", mono, phase=None, **fields)

    def end(self, mono, **fields):
        if self.phase is not None:
            # The auto-close shares the session_end's clock, exactly as the
            # recorder writes it — otherwise the fixture invents a clock jump.
            self.close(mono, outcome="unclosed",
                       mono_epoch=fields.get("mono_epoch", EPOCH))
        row = self.add("session_end", mono, **fields)
        row["phase"] = None
        return row

    def open(self, mono, name, kind=PR.CLASS_ACTIVE, **fields):
        row = self.add("phase_open", mono, kind=kind, **fields)
        row["phase"] = name
        self.phase = name
        return row

    def close(self, mono, outcome="ok", **fields):
        row = self.add("phase_close", mono, outcome=outcome, **fields)
        self.phase = None
        return row

    def set(self, mono, name, kind=PR.CLASS_ACTIVE, **fields):
        if self.phase is not None:
            self.close(mono)
        return self.open(mono, name, kind=kind, **fields)

    def run(self, mono, duration, kind=PR.CLASS_LOCAL, exit_code=0,
            cmd_head="python", **fields):
        return self.add("run", mono, kind=kind, duration_s=duration,
                        exit_code=exit_code, cmd_head=cmd_head, **fields)

    def mark(self, mono, name):
        return self.add("mark", mono, mark=name,
                        kind=PR.CLASS_APPROVAL if name.startswith("approval")
                        else None)

    def write(self) -> Path:
        lines = [json.dumps(row, ensure_ascii=False) for row in self.rows]
        lines.extend(self.raw_lines)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return self.path


class SummaryTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.log_dir = self.root / "phases"
        self.addCleanup(self._tmp.cleanup)
        # Never read the operator's real config for personal tokens.
        patcher = mock.patch.object(PS, "active_tokens", lambda: [])
        patcher.start()
        self.addCleanup(patcher.stop)

    def log(self, session="phase-test") -> SessionLog:
        return SessionLog(PR.log_path_for(self.log_dir, session), session)

    def summarize(self, log: SessionLog, **kwargs):
        events, integrity = PS.load_events(log.write())
        return PS.summarize(events, integrity, **kwargs)

    def clean_session(self) -> SessionLog:
        """A contiguous, fully instrumented session with known exact numbers.

            0    session start, phase `inventory` (active)
            30   local run, 20 s   -> occupies [10, 30)
            60   set `mutation`    -> contiguous close+open
            100  external run, 25 s -> occupies [75, 100)
            150  approval-start
            170  approval-end
            180  set `external_wait` (kind external)
            240  close + session end

        Totals: local 20 · external 25 + 60 = 85 · approval 20 ·
                unattributed 0 · active 240 - 125 = 115.
        """
        log = self.log()
        log.start(0.0)
        log.open(0.0, "inventory")
        log.run(30.0, 20.0)
        log.set(60.0, "mutation")
        log.run(100.0, 25.0, kind=PR.CLASS_EXTERNAL, cmd_head="gh")
        log.mark(150.0, PR.MARK_APPROVAL_START)
        log.mark(170.0, PR.MARK_APPROVAL_END)
        log.set(180.0, "external_wait", kind=PR.CLASS_EXTERNAL)
        log.end(240.0)
        return log

    def assert_partition(self, summary) -> None:
        classes = summary["classes_s"]
        self.assertAlmostEqual(
            sum(classes[key] for key in PS.CLASSES),
            summary["reference_total_s"],
            places=6,
            msg=f"classes do not partition the reference total: {classes}",
        )
        self.assertAlmostEqual(
            sum(summary["unattributed_s"].values()),
            classes["unattributed"],
            places=6,
        )
        for key, value in classes.items():
            self.assertGreaterEqual(value, 0.0, f"{key} is negative")


class PartitionTests(SummaryTestCase):
    def test_partition_invariant_holds_on_a_synthetic_session(self) -> None:
        summary = self.summarize(self.clean_session())
        self.assert_partition(summary)
        self.assertEqual(summary["reference_total_s"], 240.0)
        self.assertEqual(summary["classes_s"], {
            "active": 115.0,
            "local_subprocess": 20.0,
            "external_wait": 85.0,
            "approval_wait": 20.0,
            "unattributed": 0.0,
        })

    def test_phase_rows_sum_to_totals(self) -> None:
        summary = self.summarize(self.clean_session())
        rows = summary["phases"]
        self.assertEqual(
            sum(r["elapsed_s"] for r in rows), summary["coverage"]["phase_covered_s"]
        )
        for row_key, class_key in (
            ("active_s", "active"),
            ("local_subprocess_s", "local_subprocess"),
            ("external_wait_s", "external_wait"),
            ("approval_wait_s", "approval_wait"),
            ("unattributed_s", "unattributed"),
        ):
            with self.subTest(column=row_key):
                self.assertAlmostEqual(
                    sum(r[row_key] for r in rows),
                    summary["classes_s"][class_key],
                    places=6,
                )
        self.assertEqual(
            sum(r["wrapped_commands"] for r in rows),
            sum(summary["wrapped_commands_by_head"].values()),
        )

    def test_wrapped_subprocess_total_equals_local_plus_external_wrapped(self) -> None:
        """A4: wrapped runtime is an OVERLAY, and it overlaps external_wait."""
        summary = self.summarize(self.clean_session())
        self.assertEqual(summary["wrapped_subprocess_s"], 45.0)
        self.assertEqual(
            summary["wrapped_local_s"] + summary["wrapped_external_s"],
            summary["wrapped_subprocess_s"],
        )
        self.assertEqual(summary["wrapped_local_s"],
                         summary["classes_s"]["local_subprocess"])
        # The overlay is deliberately NOT a partition member.
        self.assertLess(summary["wrapped_external_s"],
                        summary["classes_s"]["external_wait"])

    def test_a_child_claiming_more_time_than_exists_is_clipped_and_flagged(self) -> None:
        """An impossible duration is reconciled, not published, and not silent.

        This used to drive ``active`` negative and trip ``accounting_error``.
        The tiling now clips the child to the span it actually occupies, which
        is the honest reading — so the partition holds and the anomaly is
        reported as ``overlong_runs`` instead of as a negative residual.
        """
        log = self.log()
        log.start(0.0)
        log.open(0.0, "mutation")
        log.run(10.0, 100.0)          # a child claiming more time than exists
        log.end(10.0)
        summary = self.summarize(log)

        self.assertEqual(summary["integrity"]["overlong_runs"], 1)
        self.assertTrue(any("overlong_runs" in n for n in summary["notes"]))
        self.assertLessEqual(summary["classes_s"]["local_subprocess"],
                             summary["reference_total_s"] + 1e-6,
                             "a class may never exceed the total it partitions")
        for value in summary["classes_s"].values():
            self.assertGreaterEqual(value, 0.0)
        self.assert_partition(summary)

    def test_concurrent_children_do_not_inflate_subprocess_time(self) -> None:
        """Overlapping wrapped children must be counted once, not once each.

        Three concurrent 10s children inside a 12s phase summed to 30s of
        subprocess time against a 12s reference, and because ``active`` is the
        residual it collapsed to 0. The recorder advertises atomic appends under
        concurrent subagents, so this is an ordinary session, not a corner case.
        """
        log = self.log()
        log.start(0.0)
        log.open(0.0, "validation")
        for _ in range(3):
            log.run(11.0, 10.0)       # three children, all ending at t=11
        log.close(11.0)
        log.end(12.0)
        summary = self.summarize(log)

        self.assertLessEqual(summary["classes_s"]["local_subprocess"], 12.0 + 1e-6)
        self.assertGreater(summary["wrapped_local_s"], 12.0,
                           "the raw overlay should still show the 30s of child time")
        self.assert_partition(summary)


class CoverageTests(SummaryTestCase):
    def test_coverage_uses_external_total_when_supplied_and_says_so(self) -> None:
        log = self.clean_session()
        log.rows[-1]["external_total_s"] = 300.0
        summary = self.summarize(log)

        self.assertEqual(summary["reference_source"], "external_supplied")
        self.assertEqual(summary["reference_total_s"], 300.0)
        self.assertEqual(summary["recorder_span_s"], 240.0)
        self.assertEqual(summary["pre_arm_s"], 60.0)
        self.assertEqual(summary["coverage"]["phase_coverage_pct"], 80.0)
        self.assert_partition(summary)

    def test_coverage_falls_back_to_recorder_span_and_labels_the_source(self) -> None:
        summary = self.summarize(self.clean_session())
        self.assertEqual(summary["reference_source"], "recorder_span")
        self.assertEqual(summary["coverage"]["phase_coverage_pct"], 100.0)
        self.assertEqual(summary["pre_arm_s"], 0.0)
        # 100% against your own span proves nothing, and the summary says so.
        self.assertTrue(any("denominator" in note for note in summary["notes"]))

    def test_rendered_output_always_names_the_denominator(self) -> None:
        for external, expected in ((None, "recorder span"), (300.0, "external total")):
            with self.subTest(external=external):
                log = self.clean_session()
                if external is not None:
                    log.rows[-1]["external_total_s"] = external
                summary = self.summarize(log)
                for rendered in (PS.render_text(summary), PS.render_markdown(summary)):
                    self.assertIn("phase coverage", rendered)
                    self.assertIn(expected, rendered)

    def test_external_total_smaller_than_span_does_not_clamp(self) -> None:
        log = self.clean_session()
        log.rows[-1]["external_total_s"] = 100.0
        summary = self.summarize(log)

        self.assertEqual(summary["reference_source"], "recorder_span")
        self.assertEqual(summary["reference_total_s"], 240.0)
        self.assertTrue(any("clock_disagreement" in n for n in summary["notes"]))
        self.assert_partition(summary)

    def test_min_coverage_exit_codes(self) -> None:
        log = self.clean_session()
        log.rows[-1]["external_total_s"] = 300.0    # coverage 80%
        log.write()
        for threshold, expected in ((80.0, 0), (75.0, 0), (95.0, 1)):
            with self.subTest(threshold=threshold):
                self.assertEqual(self.main(["--min-coverage", str(threshold)]), expected)

    def main(self, extra):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = PS.main(["--log-dir", str(self.log_dir), "--last", *extra])
        self.stdout, self.stderr = out.getvalue(), err.getvalue()
        return code


class GapTests(SummaryTestCase):
    def _gap_session(self, gap: float, run_duration: float | None = None):
        log = self.log()
        log.start(0.0)
        log.open(0.0, "mutation")
        if run_duration is not None:
            log.run(gap, run_duration)
        log.end(gap)
        return self.summarize(log)

    def test_long_gap_becomes_unattributed_not_active(self) -> None:
        """The central honesty property: silence is not evidence of reasoning."""
        summary = self._gap_session(300.0)
        self.assertEqual(summary["unattributed_s"]["long_gap"], 300.0)
        self.assertEqual(summary["classes_s"]["active"], 0.0)
        self.assert_partition(summary)
        self.assertTrue(any("long_gap" in note for note in summary["notes"]))

    def test_gap_shorter_than_threshold_stays_active(self) -> None:
        summary = self._gap_session(60.0)
        self.assertEqual(summary["unattributed_s"]["long_gap"], 0.0)
        self.assertEqual(summary["classes_s"]["active"], 60.0)

    def test_gap_spanned_by_a_wrapped_child_is_subprocess_not_long_gap(self) -> None:
        summary = self._gap_session(300.0, run_duration=300.0)
        self.assertEqual(summary["unattributed_s"]["long_gap"], 0.0)
        self.assertEqual(summary["classes_s"]["local_subprocess"], 300.0)
        self.assertEqual(summary["classes_s"]["active"], 0.0)

    def test_the_uncovered_part_of_a_gap_is_still_a_long_gap(self) -> None:
        summary = self._gap_session(300.0, run_duration=100.0)
        self.assertEqual(summary["classes_s"]["local_subprocess"], 100.0)
        self.assertEqual(summary["unattributed_s"]["long_gap"], 200.0)
        self.assertEqual(summary["classes_s"]["active"], 0.0)

    def test_idle_threshold_is_configurable(self) -> None:
        log = self.log()
        log.start(0.0)
        log.open(0.0, "mutation")
        log.end(60.0)
        events, integrity = PS.load_events(log.write())
        relaxed = PS.summarize(events, integrity, idle_threshold=120.0)
        strict = PS.summarize(events, integrity, idle_threshold=30.0)
        self.assertEqual(relaxed["unattributed_s"]["long_gap"], 0.0)
        self.assertEqual(strict["unattributed_s"]["long_gap"], 60.0)

    def test_time_between_phases_is_named_not_absorbed(self) -> None:
        log = self.log()
        log.start(0.0)
        log.open(0.0, "inventory")
        log.close(10.0)
        log.open(40.0, "mutation")     # a 30 s hole between two phases
        log.close(50.0)
        log.end(50.0)
        summary = self.summarize(log)

        self.assertEqual(summary["unattributed_s"]["between_phases"], 30.0)
        self.assertEqual(summary["coverage"]["phase_covered_s"], 20.0)
        self.assertEqual(summary["coverage"]["phase_coverage_pct"], 40.0)
        self.assert_partition(summary)


class ApprovalTests(SummaryTestCase):
    def test_approval_wait_is_zero_without_explicit_marks(self) -> None:
        """A6: never inferred. A quiet phase is NOT evidence of an approval."""
        summary = self._gap_only()
        self.assertEqual(summary["classes_s"]["approval_wait"], 0.0)
        self.assertTrue(any("NOT MEASURED" in note for note in summary["notes"]))

    def _gap_only(self):
        log = self.log()
        log.start(0.0)
        log.open(0.0, "mutation")
        log.end(600.0)
        return self.summarize(log)

    def test_unpaired_approval_mark_contributes_zero_and_is_counted(self) -> None:
        log = self.log()
        log.start(0.0)
        log.open(0.0, "mutation")
        log.mark(10.0, PR.MARK_APPROVAL_START)
        log.mark(20.0, PR.MARK_APPROVAL_START)      # a second START, no END
        log.end(30.0)
        summary = self.summarize(log)

        self.assertEqual(summary["classes_s"]["approval_wait"], 0.0)
        self.assertEqual(summary["integrity"]["unpaired_approval_marks"], 2)
        self.assert_partition(summary)

    def test_an_end_without_a_start_is_measured_as_zero(self) -> None:
        log = self.log()
        log.start(0.0)
        log.open(0.0, "mutation")
        log.mark(20.0, PR.MARK_APPROVAL_END)
        log.end(30.0)
        summary = self.summarize(log)
        self.assertEqual(summary["classes_s"]["approval_wait"], 0.0)
        self.assertEqual(summary["integrity"]["unpaired_approval_marks"], 1)

    def test_a_declared_approval_phase_counts_as_approval_wait(self) -> None:
        log = self.log()
        log.start(0.0)
        log.open(0.0, "context", kind=PR.CLASS_APPROVAL)
        log.end(45.0)
        summary = self.summarize(log)
        self.assertEqual(summary["classes_s"]["approval_wait"], 45.0)
        self.assertEqual(summary["unattributed_s"]["long_gap"], 0.0)


class ExternalWaitTests(SummaryTestCase):
    def test_external_wait_phase_does_not_double_count_a_wrapped_call_inside_it(self):
        log = self.log()
        log.start(0.0)
        log.open(0.0, "external_wait", kind=PR.CLASS_EXTERNAL)
        log.run(30.0, 30.0, kind=PR.CLASS_EXTERNAL, cmd_head="gh")
        log.end(60.0)
        summary = self.summarize(log)

        self.assertEqual(summary["classes_s"]["external_wait"], 60.0)
        self.assertEqual(summary["wrapped_external_s"], 30.0)
        self.assert_partition(summary)

    def test_an_external_run_inside_an_active_phase_still_counts_as_external(self):
        log = self.log()
        log.start(0.0)
        log.open(0.0, "commit")
        log.run(40.0, 40.0, kind=PR.CLASS_EXTERNAL, cmd_head="gh")
        log.end(60.0)
        summary = self.summarize(log)

        self.assertEqual(summary["classes_s"]["external_wait"], 40.0)
        self.assertEqual(summary["classes_s"]["active"], 20.0)


class ClockAndIntegrityTests(SummaryTestCase):
    def test_mono_epoch_shift_becomes_clock_skew_not_a_giant_active_interval(self):
        """A suspended machine must not read as ten minutes of thinking."""
        log = self.log()
        log.start(0.0)
        log.open(0.0, "mutation")
        log.add("mark", 10.0, mark="note")
        # The machine slept 600 s: monotonic advanced 5 s, the wall clock 605 s.
        log.add("mark", 15.0, mark="note", mono_epoch=EPOCH + 600)
        log.end(20.0, mono_epoch=EPOCH + 600)
        summary = self.summarize(log)

        self.assertEqual(summary["integrity"]["clock_skew_events"], 1)
        self.assertEqual(summary["unattributed_s"]["clock_skew"], 605.0)
        self.assertEqual(summary["unattributed_s"]["long_gap"], 0.0)
        self.assertEqual(summary["classes_s"]["active"], 15.0)
        self.assert_partition(summary)

    def test_malformed_and_truncated_lines_are_skipped_and_counted(self) -> None:
        log = self.log()
        log.start(0.0)
        log.open(0.0, "mutation")
        log.end(30.0)
        log.raw_lines = [
            "{not json",
            '{"v": 1, "session": "x", "seq": 99, "event": "run"}',   # no mono
            '["a list is not an event"]',
            '{"v": 2, "session": "x", "mono": 1.0, "event": "run"}',  # future schema
        ]
        summary = self.summarize(log)

        self.assertEqual(summary["integrity"]["malformed_lines"], 3)
        self.assertEqual(summary["integrity"]["unsupported_version_lines"], 1)
        self.assertEqual(summary["reference_total_s"], 30.0)
        self.assert_partition(summary)

    def test_missing_seq_is_reported(self) -> None:
        log = self.log()
        log.start(0.0)
        log.open(0.0, "mutation")
        log.end(30.0)
        log.rows[1]["seq"] = 7          # events 1..6 lost
        summary = self.summarize(log)
        self.assertGreater(summary["integrity"]["missing_seq"], 0)

    def test_missing_session_end_autocloses_and_flags_the_implicit_end(self) -> None:
        log = self.log()
        log.start(0.0)
        log.open(0.0, "mutation")
        log.add("mark", 50.0, mark="note")
        summary = self.summarize(log)

        self.assertTrue(summary["integrity"]["session_end_missing"])
        self.assertEqual([r["outcome"] for r in summary["phases"]], ["unclosed"])
        self.assertEqual(summary["coverage"]["phase_covered_s"], 50.0)
        self.assertTrue(any("session_end is missing" in n for n in summary["notes"]))
        self.assert_partition(summary)

    def test_a_tail_with_no_open_phase_is_named_after_last_event(self) -> None:
        log = self.log()
        log.start(0.0)
        log.open(0.0, "mutation")
        log.close(100.0)
        log.end(150.0)
        summary = self.summarize(log)

        self.assertEqual(summary["unattributed_s"]["after_last_event"], 50.0)
        self.assertEqual(summary["unattributed_s"]["between_phases"], 0.0)
        self.assert_partition(summary)

    def test_an_empty_log_is_not_a_crash(self) -> None:
        path = PR.log_path_for(self.log_dir, "empty")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")
        events, integrity = PS.load_events(path)
        summary = PS.summarize(events, integrity)
        self.assertEqual(summary["reference_total_s"], 0.0)
        self.assertEqual(summary["coverage"]["phase_coverage_pct"], 0.0)
        PS.render_text(summary)
        PS.render_markdown(summary)


# Structural-PII probes are ASSEMBLED AT RUNTIME, never written as literals: a
# literal here would be a real email / phone / home path / handle shape sitting
# in a tracked public file, and the leak guard would (correctly) fail this repo
# over its own test fixture. Concatenation keeps the source clean while the
# assembled value is exactly what the guard is meant to catch — and the test
# asserts the guard DOES catch the assembled value, so it cannot go vacuous.
_PROBE_EMAIL = "ada" + "@" + "realcorp" + ".com"
_PROBE_PHONE = "+1 415 " + "867" + "-" + "5309"
_PROBE_HOME = "/Users/" + "adareal"
_PROBE_LINKEDIN = "linkedin.com/in/" + "ada" + "-real"


class RedactionTests(SummaryTestCase):
    POISON = "Zzyzx-Widgets-Placeholder"

    def poisoned_log(self) -> SessionLog:
        """Every free-text channel the recorder has, loaded with one token."""
        log = self.log(session=f"{self.POISON}-session")
        log.start(0.0, label=self.POISON,
                  harness_session_id=f"harness-{self.POISON}",
                  repo_role="overlay", repo_fingerprint="deadbeef")
        log.open(0.0, f"{self.POISON}-phase", label=self.POISON)
        log.run(30.0, 20.0, cmd_head="git", label=self.POISON,
                cmd=["git", "commit", "-m", self.POISON,
                     f"/Users/{self.POISON}/private/applications"])
        log.end(60.0)
        return log

    def test_redacted_summary_contains_no_free_text(self) -> None:
        log = self.poisoned_log()
        summary = self.summarize(log)
        rendered = [
            json.dumps(summary, ensure_ascii=False),
            PS.render_text(summary),
            PS.render_markdown(summary),
        ]
        for text in rendered:
            self.assertNotIn(self.POISON, text)
            self.assertNotIn(self.POISON.lower(), text.lower())
            self.assertNotIn("/Users/", text)

        # The test is live: the poison IS in the raw log it was built from.
        self.assertIn(self.POISON, log.path.read_text(encoding="utf-8"))
        # ...and the structural stand-ins are present instead.
        self.assertEqual(summary["session_digest"],
                         PR.digest(f"{self.POISON}-session"))
        self.assertEqual(summary["unknown_phase_count"], 1)
        self.assertEqual(summary["phases"][0]["phase"], PS.UNKNOWN_PHASE_LABEL)
        self.assertEqual(summary["phases"][0]["phase_digest"],
                         PR.digest(f"{self.POISON}-phase"))
        self.assertEqual(summary["repos"],
                         [{"role": "overlay", "fingerprint": "deadbeef"}])
        self.assertEqual(summary["wrapped_commands_by_head"], {"git": 1})

    def test_redacted_summary_passes_the_leak_guard_structural_scan(self) -> None:
        raw_pii = f"{_PROBE_EMAIL} {_PROBE_PHONE} {_PROBE_HOME} {_PROBE_LINKEDIN}"
        log = self.log()
        log.start(0.0, label=f"contact {_PROBE_EMAIL} {_PROBE_PHONE}")
        log.open(0.0, "mutation", label=f"{_PROBE_HOME}/private {_PROBE_LINKEDIN}")
        log.run(10.0, 5.0, cmd=["git", "push", f"{_PROBE_HOME}/repo"],
                label=_PROBE_PHONE)
        log.end(20.0)
        summary = self.summarize(log)
        rendered = (json.dumps(summary, ensure_ascii=False)
                    + PS.render_text(summary) + PS.render_markdown(summary))

        # The probes really are leak shapes — otherwise this test proves nothing.
        raw_hits = PS.redaction_hits(raw_pii, tokens=[])
        self.assertIsNotNone(raw_hits, "the leak guard must be importable")
        self.assertEqual(
            sorted({kind for kind, _match in raw_hits}),
            ["email", "home_path", "linkedin", "phone"],
        )
        # ...and none of them survives into the summary.
        self.assertEqual(PS.redaction_hits(rendered, tokens=[]), [])

    def test_notes_never_interpolate_free_text(self) -> None:
        summary = self.summarize(self.poisoned_log())
        for note in summary["notes"]:
            self.assertNotIn(self.POISON, note)

    def test_strict_exits_one_and_writes_nothing_on_a_redaction_hit(self) -> None:
        self.clean_write()
        out = self.root / "summary.md"
        with mock.patch.object(PS, "active_tokens", lambda: ["external_wait"]):
            code = self.main(["--strict", "--markdown", "--out", str(out)])
        self.assertEqual(code, 1)
        self.assertFalse(out.exists())
        self.assertIn("redaction self-check", self.stderr)

    def test_strict_passes_a_clean_summary(self) -> None:
        self.clean_write()
        out = self.root / "summary.md"
        code = self.main(["--strict", "--markdown", "--out", str(out)])
        self.assertEqual(code, 0)
        self.assertTrue(out.exists())

    def test_strict_fails_closed_when_the_self_check_cannot_run(self) -> None:
        """A check that silently did nothing reads as a pass; it must not."""
        self.clean_write()
        with mock.patch.object(PS, "_leak_guard", lambda: None):
            self.assertEqual(self.main(["--strict"]), 1)

    def clean_write(self) -> None:
        log = self.log()
        log.start(0.0)
        log.open(0.0, "mutation")
        log.run(30.0, 20.0)
        log.end(60.0)
        log.write()

    def main(self, extra):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = PS.main(["--log-dir", str(self.log_dir), "--last", *extra])
        self.stdout, self.stderr = out.getvalue(), err.getvalue()
        return code


class UnredactedTests(SummaryTestCase):
    def test_unredacted_refuses_a_tracked_output_path(self) -> None:
        self.assertFalse(PS._unredacted_allowed(PS.REPO_ROOT / "docs" / "leak.json"))
        self.assertFalse(PS._unredacted_allowed(PS.REPO_ROOT / "private" / "x.json"))
        self.assertTrue(PS._unredacted_allowed(PS.REPO_ROOT / "logs" / "x.json"))
        self.assertTrue(PS._unredacted_allowed(PS.REPO_ROOT / "local" / "x.json"))
        self.assertTrue(PS._unredacted_allowed(self.root / "x.json"))

    def test_unredacted_requires_out_and_refuses_a_tracked_path_end_to_end(self) -> None:
        log = self.log()
        log.start(0.0)
        log.open(0.0, "mutation")
        log.end(30.0)
        log.write()
        tracked = PS.REPO_ROOT / "docs" / "handbook" / "leak.json"

        err = io.StringIO()
        with redirect_stdout(io.StringIO()), redirect_stderr(err):
            no_out = PS.main(["--log-dir", str(self.log_dir), "--last", "--unredacted"])
            refused = PS.main(["--log-dir", str(self.log_dir), "--last", "--unredacted",
                               "--out", str(tracked)])
        self.assertEqual((no_out, refused), (2, 2))
        self.assertFalse(tracked.exists())

    def test_unredacted_writes_the_raw_events_to_scratch(self) -> None:
        log = self.log()
        log.start(0.0, label="secret-label")
        log.open(0.0, "mutation")
        log.end(30.0)
        log.write()
        out = self.root / "raw.json"

        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            code = PS.main(["--log-dir", str(self.log_dir), "--last", "--unredacted",
                            "--out", str(out)])
        self.assertEqual(code, 0)
        payload = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(payload["schema"], "phase-summary-unredacted/1")
        self.assertIn("secret-label", out.read_text(encoding="utf-8"))


class RenderingTests(SummaryTestCase):
    def test_markdown_render_matches_json_numbers(self) -> None:
        """One source of numbers: no second, divergent rendering path."""
        log = self.clean_session()
        log.rows[-1]["external_total_s"] = 300.0
        summary = self.summarize(log)
        markdown = PS.render_markdown(summary)

        total = next(line for line in markdown.splitlines()
                     if line.startswith("| TOTAL"))
        cells = [cell.strip() for cell in total.strip("|").split("|")]
        classes = summary["classes_s"]
        self.assertEqual(cells[2], f"{summary['reference_total_s']:.1f}s")
        self.assertEqual(cells[3], f"{classes['active']:.1f}s")
        self.assertEqual(cells[4], f"{classes['local_subprocess']:.1f}s")
        self.assertEqual(cells[5], f"{classes['external_wait']:.1f}s")
        self.assertEqual(cells[6], f"{classes['approval_wait']:.1f}s")
        self.assertEqual(cells[7], f"{classes['unattributed']:.1f}s")

        text = PS.render_text(summary)
        for line in PS._footer_lines(summary):
            self.assertIn(line, text)
            self.assertIn(line, markdown)

    def test_tokens_and_tool_calls_are_reported_as_not_measured(self) -> None:
        summary = self.summarize(self.clean_session())
        self.assertEqual(summary["tokens"], "not_measured")
        self.assertEqual(summary["tool_calls"], "not_measured")
        self.assertIn("not measured", PS.render_text(summary))


class CliTests(SummaryTestCase):
    def test_missing_session_exits_two(self) -> None:
        err = io.StringIO()
        with redirect_stdout(io.StringIO()), redirect_stderr(err):
            code = PS.main(["--log-dir", str(self.log_dir), "--session", "nope"])
        self.assertEqual(code, 2)

    def test_last_ignores_a_stale_pointer(self) -> None:
        old = self.log("old")
        old.start(0.0)
        old.open(0.0, "mutation")
        old.end(10.0)
        old.write()
        PR._write_pointer(self.log_dir, "old")
        new = self.log("new")
        new.start(0.0)
        new.open(0.0, "commit")
        new.end(20.0)
        new.write()

        out = io.StringIO()
        with redirect_stdout(out), redirect_stderr(io.StringIO()):
            code = PS.main(["--log-dir", str(self.log_dir), "--last", "--json"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out.getvalue())["session_digest"],
                         PR.digest("new"))


if __name__ == "__main__":
    unittest.main()
