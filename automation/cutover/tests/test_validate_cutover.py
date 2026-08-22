"""Tests for the named ``cutover`` validation profile.

The properties under test are the ones a wrong answer would hide rather than
announce:

  * a gate that exits nonzero inside a PARALLEL run is reported with its own real
    exit code — the thread pool must not launder a red lane into a green summary;
  * a SKIP is counted and named separately and never rolls up as a PASS;
  * the profile refuses, before any subprocess starts, to validate the fictional
    example persona;
  * the bundled commands are the real flags those scripts define, not invented
    ones — the same drift discipline ``test_run_gates.CIDriftTests`` applies.

Nothing here touches the real config, the private overlay, or the owner's data:
gates are synthetic ``python -c`` processes and every log lives in a temp tree.

Run with:
    .venv/bin/python -m unittest discover automation/cutover/tests
"""
from __future__ import annotations

import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

# Make the sibling module importable (automation/cutover/).
_CUTOVER_DIR = Path(__file__).resolve().parents[1]
if str(_CUTOVER_DIR) not in sys.path:
    sys.path.insert(0, str(_CUTOVER_DIR))

import validate_cutover  # noqa: E402

RUN_GATES = validate_cutover.RUN_GATES
REPO_ROOT = validate_cutover.REPO_ROOT


def exiting_gate(name: str, code: int, **kwargs):
    """A synthetic gate whose subprocess exits with exactly ``code``."""
    return validate_cutover.Gate(
        name=name,
        argv=(sys.executable, "-c", f"import sys; print('gate {name}'); "
                                    f"sys.exit({code})"),
        what_it_proves=f"synthetic gate exiting {code}",
        group="cutover",
        **kwargs)


class StubConfig:
    """Enough of ``automation/shared/config.py`` for the profile precondition."""

    EXAMPLE_CONFIG_FILENAME = "config.example.yaml"

    def __init__(self, path="/nowhere/real/config.yaml", mounted=True, raises=None):
        self._path = Path(path)
        self._mounted = mounted
        self._raises = raises
        self.EXAMPLE_CONFIG = Path("/nowhere/real/config.example.yaml")

    def config_path(self):
        if self._raises is not None:
            raise self._raises
        return self._path

    def overlay_mounted(self):
        return self._mounted


class GateTableTests(unittest.TestCase):
    def setUp(self):
        self.manifest = Path("/tmp/does-not-exist/copied.txt")

    def names(self, profile: str) -> list[str]:
        return [gate.name for gate in validate_cutover.build_gates(
            REPO_ROOT, profile=profile, manifest=self.manifest)]

    def test_the_cutover_profile_is_exactly_these_five_gates(self):
        self.assertEqual(
            self.names(validate_cutover.PROFILE_CUTOVER),
            ["app-metadata", "calendar", "configured-paths", "copy-checksum",
             "overlay-bootstrap"])

    def test_the_full_profile_adds_locations_and_company_keys(self):
        self.assertEqual(
            self.names(validate_cutover.PROFILE_FULL),
            ["app-metadata", "calendar", "configured-paths", "copy-checksum",
             "overlay-bootstrap", "locations", "company-keys"])

    def test_every_bundled_flag_is_one_the_target_script_actually_defines(self):
        """Drift check: a gate that invokes an invented flag exits 2 forever."""
        expected = {
            "app-metadata": (validate_cutover.TRACKER, ["--check-metadata"]),
            "calendar": (validate_cutover.TRACKER, ["--check-calendar"]),
            "locations": (validate_cutover.TRACKER, ["--check-locations"]),
            "company-keys": (validate_cutover.TRACKER,
                             ["--company-keys", "--strict"]),
            "overlay-bootstrap": (validate_cutover.BOOTSTRAP, ["--check"]),
            "configured-paths": (validate_cutover.CHECK_PATHS, []),
            "copy-checksum": (validate_cutover.VERIFY_COPY, ["--verify"]),
        }
        gates = {gate.name: gate for gate in validate_cutover.build_gates(
            REPO_ROOT, profile=validate_cutover.PROFILE_FULL,
            manifest=self.manifest)}
        self.assertEqual(set(gates), set(expected))
        for name, (script, flags) in expected.items():
            with self.subTest(gate=name):
                path = REPO_ROOT / script
                self.assertTrue(path.is_file(), f"{script} does not exist")
                self.assertEqual(gates[name].argv[1], script)
                source = path.read_text(encoding="utf-8")
                for flag in flags:
                    self.assertIn(flag, gates[name].argv)
                    self.assertTrue(
                        f'add_argument("{flag}"' in source
                        or f"add_argument('{flag}'" in source,
                        f"{script} does not define {flag}")

    def test_no_gate_argv_is_a_shell_string_or_carries_a_pipe(self):
        for gate in validate_cutover.build_gates(
                REPO_ROOT, profile=validate_cutover.PROFILE_FULL,
                manifest=self.manifest):
            with self.subTest(gate=gate.name):
                self.assertIsInstance(gate.argv, tuple)
                for token in gate.argv:
                    self.assertIsInstance(token, str)
                    self.assertNotIn("|", token)
                self.assertEqual(gate.argv[0], sys.executable)

    def test_every_gate_is_read_only_and_therefore_parallel_safe(self):
        for gate in validate_cutover.build_gates(
                REPO_ROOT, profile=validate_cutover.PROFILE_FULL,
                manifest=self.manifest):
            with self.subTest(gate=gate.name):
                self.assertTrue(gate.parallel_safe)
                self.assertIsNone(gate.dirties)

    def test_an_unknown_profile_is_an_error_not_an_empty_table(self):
        with self.assertRaises(SystemExit):
            validate_cutover.build_gates(REPO_ROOT, profile="whatever")

    def test_the_runner_is_reused_rather_than_reimplemented(self):
        self.assertIs(validate_cutover.run_many, RUN_GATES.run_many)
        self.assertIs(validate_cutover.summarise, RUN_GATES.summarise)
        source = (_CUTOVER_DIR / "validate_cutover.py").read_text(encoding="utf-8")
        self.assertNotIn("ThreadPoolExecutor", source)
        self.assertNotIn("subprocess.run(", source)


class ManifestPreconditionTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.manifest = self.root / "copied.txt"

    def gate(self):
        gates = {g.name: g for g in validate_cutover.build_gates(
            REPO_ROOT, manifest=self.manifest)}
        return gates["copy-checksum"]

    def test_an_absent_manifest_skips_before_the_subprocess_starts(self):
        result = RUN_GATES._evaluate_precondition(self.gate(), self.root)
        self.assertIsNotNone(result)
        self.assertEqual(result.status, RUN_GATES.SKIP)
        self.assertIn("never a PASS", result.reason)

    def test_a_present_manifest_runs_the_gate(self):
        self.manifest.write_text("", encoding="utf-8")
        self.assertIsNone(RUN_GATES._evaluate_precondition(self.gate(), self.root))

    def test_the_manifest_path_is_carried_into_the_argv(self):
        self.assertIn(str(self.manifest), self.gate().argv)


class ProfilePreconditionTests(unittest.TestCase):
    def test_a_real_config_with_a_mounted_overlay_may_run(self):
        self.assertIsNone(validate_cutover.refusal_reason(StubConfig()))

    def test_the_example_persona_is_refused(self):
        reason = validate_cutover.refusal_reason(
            StubConfig(path="/repo/config.example.yaml"))
        self.assertIsNotNone(reason)
        self.assertIn("example persona", reason)

    def test_an_unloadable_config_is_refused(self):
        reason = validate_cutover.refusal_reason(
            StubConfig(raises=RuntimeError("no config.yaml found")))
        self.assertIsNotNone(reason)
        self.assertIn("no configuration", reason)

    def test_an_unmounted_overlay_is_refused(self):
        reason = validate_cutover.refusal_reason(StubConfig(mounted=False))
        self.assertIsNotNone(reason)
        self.assertIn("no private overlay", reason)


class ExecutionTests(unittest.TestCase):
    """Exit-code aggregation over the real runner, with synthetic gates."""

    def run_gates_in_temp(self, gates, *, jobs=1):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        log_dir = root / "gates"
        results = validate_cutover.run_many(
            gates, log_dir, jobs=jobs, fail_fast=False, root=root,
            on_done=lambda result: None)
        out = io.StringIO()
        code = validate_cutover.summarise(results, out, tail=15, root=root)
        return results, code, out.getvalue(), log_dir

    def test_all_green_exits_zero(self):
        _, code, text, _ = self.run_gates_in_temp([exiting_gate("a", 0)])
        self.assertEqual(code, 0, text)
        self.assertIn("ALL GREEN (1 of 1 gates ran)", text)

    def test_a_failing_gate_in_a_parallel_run_is_reported_as_exit_one(self):
        gates = [exiting_gate(f"pass-{i}", 0) for i in range(4)]
        gates.insert(2, exiting_gate("red", 1))

        results, code, text, _ = self.run_gates_in_temp(gates, jobs=4)

        self.assertEqual(code, 1, text)
        red = next(r for r in results if r.name == "red")
        self.assertEqual(red.exit_code, 1)
        self.assertEqual(red.status, RUN_GATES.FAIL)
        self.assertIn("RED: red (1 of 5 failed)", text)
        self.assertNotIn("ALL GREEN", text)

    def test_every_lanes_own_exit_code_survives_the_thread_pool(self):
        gates = [exiting_gate("zero", 0), exiting_gate("one", 1),
                 exiting_gate("two", 2)]

        results, code, text, _ = self.run_gates_in_temp(gates, jobs=4)

        self.assertEqual(code, 1, text)
        self.assertEqual({r.name: r.exit_code for r in results},
                         {"zero": 0, "one": 1, "two": 2})
        # The table prints each real code, so one failure never hides another's.
        rows = {line.split()[0]: line for line in text.splitlines()
                if line.split() and line.split()[0] in {"zero", "one", "two"}}
        self.assertIn(" 0  PASS", rows["zero"])
        self.assertIn(" 1  FAIL", rows["one"])
        self.assertIn(" 2  FAIL", rows["two"])

    def test_a_skip_is_named_separately_and_never_counted_green(self):
        skipped = exiting_gate(
            "skipped", 0,
            precondition=lambda root: RUN_GATES.PreconditionResult(
                RUN_GATES.SKIP, "nothing to verify for this run"))
        results, code, text, _ = self.run_gates_in_temp(
            [exiting_gate("real", 0), skipped])

        self.assertEqual(code, 0, text)
        self.assertEqual(
            {r.name: r.status for r in results},
            {"real": RUN_GATES.PASS, "skipped": RUN_GATES.SKIP})
        self.assertIn("skipped (NOT passes): skipped", text)
        # One gate passed, so the count says one — the SKIP is not folded in.
        self.assertIn("ALL GREEN (1 of 2 gates ran; 1 skipped: skipped)", text)

    def test_a_skip_never_rescues_a_failing_run(self):
        skipped = exiting_gate(
            "skipped", 0,
            precondition=lambda root: RUN_GATES.PreconditionResult(
                RUN_GATES.SKIP, "nothing to verify"))
        _, code, text, _ = self.run_gates_in_temp([skipped, exiting_gate("red", 1)])
        self.assertEqual(code, 1, text)
        self.assertIn("RED: red", text)

    def test_every_gate_that_ran_left_an_explainable_log(self):
        gates = [exiting_gate("zero", 0), exiting_gate("one", 1)]
        _, _, _, log_dir = self.run_gates_in_temp(gates, jobs=2)
        for gate in gates:
            with self.subTest(gate=gate.name):
                log = log_dir / f"{gate.name}.log"
                self.assertTrue(log.is_file())
                self.assertTrue(log.read_text().startswith("$ "))
                self.assertIn(f"gate {gate.name}", log.read_text())


class CliTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.log_dir = self.root / "gates"

    def main(self, argv, *, config=None, gate_builder=None):
        out = io.StringIO()
        with mock.patch.object(validate_cutover, "load_config",
                               return_value=config or StubConfig()):
            code = validate_cutover.main(argv, out, gate_builder=gate_builder)
        return code, out.getvalue()

    def test_the_example_persona_refuses_with_exit_three_and_runs_nothing(self):
        code, text = self.main(
            ["--log-dir", str(self.log_dir)],
            config=StubConfig(path="/repo/config.example.yaml"))
        self.assertEqual(code, 3, text)
        self.assertIn("REFUSED", text)
        self.assertIn("No gate ran", text)
        self.assertFalse(self.log_dir.exists(), "a refusal must start no subprocess")

    def test_an_unmounted_overlay_refuses_with_exit_three(self):
        code, text = self.main(["--log-dir", str(self.log_dir)],
                               config=StubConfig(mounted=False))
        self.assertEqual(code, 3, text)
        self.assertFalse(self.log_dir.exists())

    def test_a_failing_gate_makes_the_cli_exit_one(self):
        def builder(root, *, profile, manifest):
            return [exiting_gate("green", 0), exiting_gate("red", 1)]

        code, text = self.main(
            ["--log-dir", str(self.log_dir), "--jobs", "2"], gate_builder=builder)

        self.assertEqual(code, 1, text)
        self.assertIn("RED: red", text)
        self.assertTrue((self.log_dir / "red.log").is_file())

    def test_list_runs_nothing_and_exits_zero(self):
        code, text = self.main(["--list", "--log-dir", str(self.log_dir)])
        self.assertEqual(code, 0, text)
        self.assertIn("app-metadata", text)
        self.assertIn("--check-metadata", text)
        self.assertFalse(self.log_dir.exists())

    def test_only_selects_and_an_unknown_name_is_an_error(self):
        code, text = self.main(["--list", "--only", "configured-paths",
                                "--log-dir", str(self.log_dir)])
        self.assertEqual(code, 0, text)
        self.assertIn("configured-paths", text)
        self.assertNotIn("app-metadata", text)
        with self.assertRaisesRegex(SystemExit, "unknown gate"):
            self.main(["--list", "--only", "no-such-gate"])

    def test_the_manifest_default_is_stable_not_per_invocation(self):
        """The default manifest must be findable by a LATER command.

        It previously derived from ``log_dir.parent``, and log_dir carries a
        fresh per-invocation run id — so the default named a directory this run
        had just created, no manifest could ever be there, and the documented
        invocation always skipped copy-checksum: the one gate proving the
        owner's git-ignored payloads survived the move. It must be the stable
        per-checkout path instead, even when --log-dir moves the logs.
        """
        captured = {}

        def builder(root, *, profile, manifest):
            captured["manifest"] = manifest
            return [exiting_gate("green", 0)]

        code, text = self.main(["--log-dir", str(self.log_dir)],
                               gate_builder=builder)
        self.assertEqual(code, 0, text)
        expected = REPO_ROOT / "local" / "cutover" / validate_cutover.MANIFEST_FILENAME
        self.assertEqual(captured["manifest"], expected)
        self.assertNotIn(validate_cutover.run_id()[:6], str(captured["manifest"]),
                         "the default manifest must not carry a run id")

    def test_a_run_where_nothing_passed_is_not_green(self):
        """All-SKIP must refuse: an unrun check is not a passed check.

        verify_copy.py exits 3 for "nothing was verified" precisely so it could
        never read green; flattening that to 0 with the words ALL GREEN inverts
        the intent of the whole profile.
        """
        def builder(root, *, profile, manifest):
            return [exiting_gate(
                "skipper", 0,
                precondition=lambda root: RUN_GATES.PreconditionResult(
                    RUN_GATES.SKIP, "no copy manifest recorded"))]

        code, text = self.main(["--log-dir", str(self.log_dir)],
                               gate_builder=builder)
        self.assertEqual(code, 1, text)
        self.assertIn("NOT GREEN", text)
        self.assertNotIn("ALL GREEN", text)

    def test_a_partly_skipped_run_names_what_is_unproven(self):
        """Green with skips stays green, but must never read as "all checked"."""
        def builder(root, *, profile, manifest):
            return [
                exiting_gate("green", 0),
                exiting_gate(
                    "skipper", 0,
                    precondition=lambda root: RUN_GATES.PreconditionResult(
                        RUN_GATES.SKIP, "no copy manifest recorded")),
            ]

        code, text = self.main(["--log-dir", str(self.log_dir)],
                               gate_builder=builder)
        self.assertEqual(code, 0, text)
        self.assertIn("UNPROVEN", text)
        self.assertIn("skipper", text)


if __name__ == "__main__":
    unittest.main()
