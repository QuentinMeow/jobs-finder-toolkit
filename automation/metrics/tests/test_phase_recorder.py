"""Tests for the opt-in phase recorder (writer half).

Run with (from the repo root):
    .venv/bin/python -m unittest discover -s automation/metrics/tests

Every test writes into a throwaway tree, so nothing here touches the real
``logs/`` directory (or the private overlay).

What is pinned here:
  * the FAIL-SAFE invariant — every subcommand exits 0 even when the log
    directory is unwritable, because a telemetry tool that can break a session
    is worse than no telemetry at all;
  * the one exception: ``run`` returns the CHILD's exit code verbatim, INCLUDING
    when recording failed. AGENTS.md forbids reporting a failed command as
    green, and a wrapper that swallowed a red gate would do exactly that;
  * the child is never piped. Its stdout/stderr reach the recorder's own file
    descriptors, so the caller's ``$?`` and stream semantics are unchanged;
  * a network-looking command wrapped without ``--kind external`` keeps its
    declared kind and is only FLAGGED — silent reclassification would make two
    runs incomparable depending on which heuristic version ran;
  * one event is one line under 4 KiB, so the O_APPEND write stays atomic and a
    long command line truncates instead of splitting the record.
"""
from __future__ import annotations

import io
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

METRICS_DIR = Path(__file__).resolve().parents[1]
if str(METRICS_DIR) not in sys.path:
    sys.path.insert(0, str(METRICS_DIR))

import phase_recorder as PR  # noqa: E402


class RecorderTestCase(unittest.TestCase):
    """Base: a throwaway log dir with the recorder's env vars neutralised."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.log_dir = self.root / "phases"
        self.last_stderr = ""
        self.addCleanup(self._tmp.cleanup)
        patcher = mock.patch.dict(
            os.environ, {PR.SESSION_ENV: "", PR.LOG_DIR_ENV: ""}, clear=False
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        os.environ.pop(PR.SESSION_ENV, None)
        os.environ.pop(PR.LOG_DIR_ENV, None)

    # -- helpers ----------------------------------------------------------
    def run_cli(self, *args, log_dir=None):
        """Invoke ``main`` in-process; return ``(exit_code, stdout)``.

        ``--log-dir`` goes BEFORE any literal ``--``; appending it would hand
        the flag to the child command instead of the recorder.
        """
        args = list(args)
        cut = args.index("--") if "--" in args else len(args)
        argv = args[:cut] + ["--log-dir", str(log_dir or self.log_dir)] + args[cut:]
        return self.call(argv)

    def call(self, argv):
        """``main(argv)`` with both streams captured; stderr on ``last_stderr``."""
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = PR.main(argv)
        self.last_stderr = err.getvalue()
        return code, out.getvalue()

    def start(self, *extra, log_dir=None):
        code, out = self.run_cli("session", "start", *extra, log_dir=log_dir)
        self.assertEqual(code, 0)
        return out.strip()

    def events(self, session, log_dir=None):
        path = PR.log_path_for(Path(log_dir or self.log_dir), session)
        rows = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
        return rows

    def _readonly(self, path: Path) -> Path:
        path.mkdir(parents=True, exist_ok=True)
        path.chmod(stat.S_IRUSR | stat.S_IXUSR)
        self.addCleanup(lambda: path.chmod(0o700))
        return path


class SessionLifecycleTests(RecorderTestCase):
    def test_session_start_allocates_id_and_pointer(self) -> None:
        session = self.start("--label", "recon")

        self.assertTrue(session.startswith("recon-"), session)
        self.assertEqual(PR.read_pointer(self.log_dir), session)
        rows = self.events(session)
        self.assertEqual([r["event"] for r in rows], ["session_start"])
        self.assertEqual(rows[0]["seq"], 0)
        self.assertEqual(rows[0]["session_digest"], PR.digest(session))

    def test_session_end_clears_the_pointer_and_autocloses_the_phase(self) -> None:
        session = self.start()
        self.run_cli("set", "mutation")
        self.run_cli("session", "end", "--outcome", "partial")

        self.assertIsNone(PR.read_pointer(self.log_dir))
        rows = self.events(session)
        self.assertEqual(
            [r["event"] for r in rows],
            ["session_start", "phase_open", "phase_close", "session_end"],
        )
        self.assertEqual(rows[-2]["outcome"], "unclosed")
        self.assertEqual(rows[-1]["outcome"], "partial")

    def test_a_second_start_mints_a_new_session(self) -> None:
        """Appending to whatever the pointer still names would fuse two runs."""
        first = self.start()
        second = self.start()
        self.assertNotEqual(first, second)

    def test_session_id_resolution_order(self) -> None:
        """--session beats $JOBHUNT_PHASE_SESSION beats the pointer file."""
        self.log_dir.mkdir(parents=True, exist_ok=True)
        PR._write_pointer(self.log_dir, "from-pointer")

        with mock.patch.dict(os.environ, {PR.SESSION_ENV: "from-env"}):
            self.assertEqual(
                PR.resolve_session("from-flag", self.log_dir), "from-flag"
            )
            self.assertEqual(PR.resolve_session(None, self.log_dir), "from-env")
        os.environ.pop(PR.SESSION_ENV, None)
        self.assertEqual(PR.resolve_session(None, self.log_dir), "from-pointer")

    def test_two_sessions_in_one_log_dir_do_not_interleave(self) -> None:
        first = self.start("--session", "alpha")
        second = self.start("--session", "beta")
        self.run_cli("set", "plan", "--session", "alpha")
        self.run_cli("set", "commit", "--session", "beta")

        self.assertEqual((first, second), ("alpha", "beta"))
        alpha, beta = self.events("alpha"), self.events("beta")
        self.assertEqual([r["seq"] for r in alpha], [0, 1])
        self.assertEqual([r["seq"] for r in beta], [0, 1])
        self.assertEqual(alpha[1]["phase"], "plan")
        self.assertEqual(beta[1]["phase"], "commit")


class FailSafeTests(RecorderTestCase):
    def test_every_subcommand_exits_zero_on_success(self) -> None:
        session = self.start()
        for args in (
            ("set", "inventory"),
            ("open", "mutation"),
            ("mark", "approval-start"),
            ("mark", "approval-end"),
            ("close",),
            ("status",),
            ("status", "--json"),
            ("run", "--", sys.executable, "-c", "pass"),
            ("session", "end"),
        ):
            with self.subTest(args=args):
                code, _out = self.run_cli(*args)
                self.assertEqual(code, 0)
        self.assertTrue(self.events(session))

    def test_every_subcommand_exits_zero_when_log_dir_unwritable(self) -> None:
        """The fail-safe invariant: telemetry never breaks the session."""
        locked = self._readonly(self.root / "locked")
        for args, warns in (
            (("session", "start", "--session", "s1"), True),
            (("set", "inventory", "--session", "s1"), True),
            (("open", "mutation", "--session", "s1"), True),
            (("mark", "note", "--session", "s1"), True),
            (("close", "--session", "s1"), True),
            (("status", "--session", "s1"), False),   # reads only; nothing to warn about
            (("session", "end", "--session", "s1"), True),
        ):
            with self.subTest(args=args):
                code, _out = self.call([*args, "--log-dir", str(locked)])
                self.assertEqual(code, 0)
                if warns:
                    self.assertIn("phase_recorder:", self.last_stderr)
        self.assertEqual(list(locked.iterdir()), [])

    def test_corrupt_log_does_not_break_a_later_call(self) -> None:
        self.log_dir.mkdir(parents=True, exist_ok=True)
        path = PR.log_path_for(self.log_dir, "corrupt")
        path.write_text("{not json\n\x00\n", encoding="utf-8")

        code, _out = self.run_cli("set", "mutation", "--session", "corrupt")
        self.assertEqual(code, 0)
        rows = [
            line for line in path.read_text(encoding="utf-8").splitlines()
            if line.startswith("{\"v\"")
        ]
        self.assertEqual(len(rows), 1)

    def test_missing_pointer_is_not_an_error(self) -> None:
        code, out = self.run_cli("status")
        self.assertEqual(code, 0)
        self.assertIn("no active session", out)


class RunTests(RecorderTestCase):
    def test_run_returns_child_exit_code_verbatim(self) -> None:
        self.start()
        for expected in (0, 1, 3, 127):
            with self.subTest(expected=expected):
                code, _out = self.run_cli(
                    "run", "--", sys.executable, "-c", f"raise SystemExit({expected})"
                )
                self.assertEqual(code, expected)

    def test_run_returns_child_exit_code_when_recording_fails(self) -> None:
        """Never report a failed command as green, even with telemetry broken."""
        locked = self._readonly(self.root / "locked")
        witness = self.root / "witness.txt"
        code, _out = self.call([
            "run", "--session", "s1", "--log-dir", str(locked), "--",
            sys.executable, "-c",
            f"open({str(witness)!r}, 'w').write('ran'); raise SystemExit(3)",
        ])

        self.assertEqual(code, 3)
        self.assertEqual(witness.read_text(encoding="utf-8"), "ran")
        self.assertEqual(list(locked.iterdir()), [])

    def test_run_does_not_capture_child_streams(self) -> None:
        """The child inherits our fds; a pipe here would break the caller's ``$?``."""
        session = self.start()
        out_path, err_path = self.root / "out.txt", self.root / "err.txt"
        child = (
            "import sys; sys.stdout.write('CHILD-OUT'); sys.stderr.write('CHILD-ERR')"
        )
        with out_path.open("w") as out_fh, err_path.open("w") as err_fh:
            completed = subprocess.run(
                [sys.executable, str(METRICS_DIR / "phase_recorder.py"), "run",
                 "--session", session, "--log-dir", str(self.log_dir), "--",
                 sys.executable, "-c", child],
                stdout=out_fh, stderr=err_fh,
            )

        self.assertEqual(completed.returncode, 0)
        self.assertEqual(out_path.read_text(encoding="utf-8"), "CHILD-OUT")
        self.assertEqual(err_path.read_text(encoding="utf-8"), "CHILD-ERR")

    def test_run_records_duration_exit_and_cmd_head(self) -> None:
        session = self.start()
        self.run_cli("set", "validation")
        code, _out = self.run_cli(
            "run", "--", sys.executable, "-c", "import time; time.sleep(0.05)"
        )

        self.assertEqual(code, 0)
        row = self.events(session)[-1]
        self.assertEqual(row["event"], "run")
        self.assertEqual(row["phase"], "validation")
        self.assertEqual(row["kind"], PR.CLASS_LOCAL)
        self.assertEqual(row["exit_code"], 0)
        self.assertEqual(row["cmd_head"], "python")
        self.assertGreaterEqual(row["duration_s"], 0.05)
        self.assertLess(row["duration_s"], 30.0)

    def test_run_phase_flag_sets_the_phase_before_the_child(self) -> None:
        session = self.start()
        self.run_cli("run", "--phase", "commit", "--", sys.executable, "-c", "pass")

        events = [r["event"] for r in self.events(session)]
        self.assertEqual(events, ["session_start", "phase_open", "run"])
        self.assertEqual(self.events(session)[-1]["phase"], "commit")

    def test_run_without_a_command_is_a_usage_error_not_a_green_zero(self) -> None:
        self.start()
        code, _out = self.run_cli("run")
        self.assertEqual(code, 2)

    def test_spawn_failure_reports_127(self) -> None:
        self.start()
        code, _out = self.run_cli("run", "--", str(self.root / "does-not-exist"))
        self.assertEqual(code, 127)

    def test_network_hint_is_advisory_only(self) -> None:
        """A13: flag a network-looking command, never reclassify its seconds."""
        session = self.start()
        fake_gh = self.root / "bin" / "gh"
        fake_gh.parent.mkdir(parents=True, exist_ok=True)
        fake_gh.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        fake_gh.chmod(0o755)

        self.run_cli("run", "--", str(fake_gh), "pr", "checks")

        row = self.events(session)[-1]
        self.assertEqual(row["kind"], PR.CLASS_LOCAL)     # NOT moved to external
        self.assertTrue(row["cmd_network_hint"])
        self.assertEqual(row["cmd_head"], "gh")

    def test_network_hint_classifier(self) -> None:
        self.assertTrue(PR.network_hint(["git", "push", "origin", "main"]))
        self.assertTrue(PR.network_hint(["gh", "pr", "checks"]))
        self.assertFalse(PR.network_hint(["git", "status"]))
        self.assertFalse(PR.network_hint(["git", "-C", "/x", "commit"]))
        self.assertFalse(PR.network_hint([sys.executable, "-c", "pass"]))


class PhaseTests(RecorderTestCase):
    def test_set_produces_contiguous_intervals_open_allows_gaps(self) -> None:
        session = self.start()
        self.run_cli("set", "inventory")
        self.run_cli("set", "mutation")
        rows = self.events(session)
        close = next(r for r in rows if r["event"] == "phase_close")
        reopen = rows[rows.index(close) + 1]
        self.assertEqual(reopen["event"], "phase_open")
        # `set` closes and opens at ONE instant, so no second is left uncovered.
        self.assertEqual(close["mono"], reopen["mono"])

        self.run_cli("close")
        self.run_cli("open", "commit")
        rows = self.events(session)
        self.assertEqual(rows[-2]["event"], "phase_close")
        self.assertEqual(rows[-1]["event"], "phase_open")
        self.assertGreater(rows[-1]["mono"], rows[-2]["mono"])

    def test_open_while_open_records_implicit_close(self) -> None:
        session = self.start()
        self.run_cli("open", "inventory")
        self.run_cli("open", "mutation")

        rows = self.events(session)
        close = next(r for r in rows if r["event"] == "phase_close")
        self.assertTrue(close["implicit_close"])
        self.assertEqual(close["phase"], "inventory")
        self.assertEqual(rows[-1]["phase"], "mutation")

    def test_unknown_phase_name_is_recorded_not_rejected(self) -> None:
        """Rejecting a name would tempt an agent to skip instrumenting at all."""
        session = self.start()
        code, _out = self.run_cli("set", "wildcard-phase")
        self.assertEqual(code, 0)
        self.assertEqual(self.events(session)[-1]["phase"], "wildcard-phase")

    def test_phase_kind_words_map_onto_time_classes(self) -> None:
        session = self.start()
        self.run_cli("set", "external_wait", "--kind", "external")
        self.assertEqual(self.events(session)[-1]["kind"], PR.CLASS_EXTERNAL)
        self.run_cli("set", "context", "--kind", "approval")
        self.assertEqual(self.events(session)[-1]["kind"], PR.CLASS_APPROVAL)

    def test_approval_marks_carry_their_name(self) -> None:
        session = self.start()
        self.run_cli("mark", "approval-start")
        self.run_cli("mark", "approval-end")
        rows = self.events(session)[-2:]
        self.assertEqual([r["mark"] for r in rows],
                         ["approval-start", "approval-end"])
        self.assertEqual({r["kind"] for r in rows}, {PR.CLASS_APPROVAL})


class EventShapeTests(RecorderTestCase):
    def test_event_line_is_single_line_json_under_4096_bytes(self) -> None:
        session = self.start()
        blob = "x" * 9000
        self.run_cli("run", "--", sys.executable, "-c", f"# {blob}\npass")

        raw = PR.log_path_for(self.log_dir, session).read_text(encoding="utf-8")
        lines = [line for line in raw.splitlines() if line.strip()]
        for line in lines:
            self.assertLessEqual(len(line.encode("utf-8")), PR.MAX_LINE_BYTES)
            json.loads(line)                       # every line still parses
        row = json.loads(lines[-1])
        self.assertTrue(row["cmd_truncated"])
        self.assertEqual(row["exit_code"], 0)      # truncation changed nothing else

    def test_mono_epoch_is_recorded_and_stable_within_a_run(self) -> None:
        """The cross-process handshake: a shared origin means a usable delta."""
        session = self.start()
        self.run_cli("set", "plan")
        self.run_cli("mark", "note")
        rows = self.events(session)
        epochs = {r["mono_epoch"] for r in rows}
        self.assertTrue(all(isinstance(e, int) for e in epochs))
        self.assertLessEqual(max(epochs) - min(epochs), 2)
        monos = [r["mono"] for r in rows]
        self.assertEqual(monos, sorted(monos))

    def test_cmd_head_allowlist(self) -> None:
        self.assertEqual(PR.cmd_head("/usr/bin/git"), "git")
        self.assertEqual(PR.cmd_head("gh"), "gh")
        self.assertEqual(PR.cmd_head("/repo/.venv/bin/python3.11"), "python")
        self.assertEqual(PR.cmd_head("/Applications/soffice"), "soffice")
        self.assertEqual(PR.cmd_head("/Users/someone/secret-tool"), "other")
        self.assertEqual(PR.cmd_head(None), "other")

    def test_serialize_never_splits_a_line(self) -> None:
        row = {"v": 1, "session": "s", "seq": 0, "event": "run",
               "cmd": ["git", "commit", "-m", "y" * 20000], "label": "z" * 500}
        line = PR.serialize(row)
        self.assertNotIn("\n", line)
        self.assertLessEqual(len(line.encode("utf-8")), PR.MAX_LINE_BYTES)
        json.loads(line)


if __name__ == "__main__":
    unittest.main()
