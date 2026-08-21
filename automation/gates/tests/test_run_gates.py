"""Tests for the local gate runner.

The load-bearing one is ``CIDriftTests``: it re-parses ``.github/workflows/ci.yml``
on every run and fails when a step's python invocation is in NEITHER
``run_gates.build_gates()`` NOR ``run_gates.NOT_RUN_LOCALLY`` with a written reason.
Without it the runner degrades into a claim — CI grows a gate, the table does not,
and "ALL GREEN" starts meaning less than it says. ``HookDriftTests`` does the same
for ``automation/hooks/pre-commit``, the runner's other source of truth.

The rest pin the properties the runner exists for: a failing gate makes the process
exit 1, a SKIP is never counted as a PASS, the selection flags select, and every
gate that ran left a full log behind.

Run with:
    .venv/bin/python -m unittest discover automation/gates/tests
"""
from __future__ import annotations

import io
import os
import re
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

# Make the sibling module importable (automation/gates/).
_GATES_DIR = Path(__file__).resolve().parents[1]
if str(_GATES_DIR) not in sys.path:
    sys.path.insert(0, str(_GATES_DIR))

import run_gates  # noqa: E402

REPO_ROOT = run_gates.REPO_ROOT
CI_WORKFLOWS = tuple(sorted((REPO_ROOT / ".github/workflows").glob("*.yml")))
PRE_COMMIT = REPO_ROOT / "automation/hooks/pre-commit"


# ── shell-ish extraction, stdlib only ────────────────────────────────────────
# pyyaml is in requirements.txt, but a YAML load would hand back the run: blocks as
# opaque strings anyway — the invocations still have to be tokenised out of them.
# So the parsing is done once, textually, and kept here.

_RUN_RE = re.compile(r"^(\s*)run:\s*(.*)$")
_BLOCK_SCALARS = {"|", "|-", "|+", ">", ">-", ">+"}
_LANE_RUNNER = "automation/gates/run_gates.py"


def _run_blocks(text: str) -> list[str]:
    """Every ``run:`` body in a GitHub workflow (inline or block scalar)."""
    lines = text.splitlines()
    blocks: list[str] = []
    i = 0
    while i < len(lines):
        match = _RUN_RE.match(lines[i])
        if not match:
            i += 1
            continue
        indent, inline = match.group(1), match.group(2).strip()
        body: list[str] = []
        if inline and inline not in _BLOCK_SCALARS:
            body.append(inline)
        i += 1
        while i < len(lines):
            line = lines[i]
            if line.strip() and (len(line) - len(line.lstrip())) <= len(indent):
                break
            body.append(line)
            i += 1
        blocks.append("\n".join(body))
    return blocks


def _tokens(block: str) -> list[str]:
    block = block.replace("\\\n", " ")
    try:
        return shlex.split(block, comments=False)
    except ValueError:
        return block.split()


def _clean(token: str) -> str:
    return token.strip("\"'").rstrip("/")


def invocation_keys(blocks: list[str]) -> list[str]:
    """The python invocations a set of shell blocks performs.

    Three shapes, because those are the three CI uses:
      ``path:<script.py>``   — ``python automation/foo/bar.py …``
      ``discover:<dir>``     — ``python -m unittest discover [-s|-t] <dir>``
      ``module:<name>``      — ``python -m <module> …`` (``unittest`` excluded; it is
                               reported through its ``discover`` targets instead)
    """
    keys: list[str] = []

    def add(key: str) -> None:
        if key not in keys:
            keys.append(key)

    for block in blocks:
        tokens = [_clean(t) for t in _tokens(block)]
        for idx, token in enumerate(tokens):
            if token.endswith(".py") and "/" in token:
                # A lane invocation delegates back to the gate table being tested;
                # treating the runner itself as an uncovered leaf gate would make
                # the drift test reject the workflow migration to ``--lane``.
                if token != _LANE_RUNNER:
                    add(f"path:{token}")
            elif token == "-m" and idx + 1 < len(tokens):
                module = tokens[idx + 1]
                if module != "unittest":
                    add(f"module:{module}")
            elif token == "discover":
                rest = tokens[idx + 1:]
                explicit = False
                while rest and rest[0] in ("-s", "-t", "-p"):
                    if len(rest) > 1:
                        if rest[0] != "-p":
                            add(f"discover:{rest[1]}")
                        explicit = True
                    rest = rest[2:]
                if not explicit and rest and not rest[0].startswith("-"):
                    add(f"discover:{rest[0]}")
    return keys


def table_keys() -> set[str]:
    """The same three shapes, read out of the gate table's argv."""
    keys: set[str] = set()
    for gate in run_gates.build_gates(REPO_ROOT):
        argv = list(gate.argv)
        for idx, token in enumerate(argv):
            if token.endswith(".py") and "/" in token:
                keys.add(f"path:{token}")
            elif token == "-m" and idx + 1 < len(argv):
                module = argv[idx + 1]
                if module != "unittest":
                    keys.add(f"module:{module}")
            elif token == "discover":
                rest = argv[idx + 1:]
                explicit = False
                while rest and rest[0] in ("-s", "-t", "-p"):
                    if len(rest) > 1:
                        if rest[0] != "-p":
                            keys.add(f"discover:{rest[1]}")
                        explicit = True
                    rest = rest[2:]
                if not explicit and rest and not rest[0].startswith("-"):
                    keys.add(f"discover:{rest[0]}")
    return keys


def _excused() -> set[str]:
    return {f"path:{path}" for path in run_gates.NOT_RUN_LOCALLY}


class CIDriftTests(unittest.TestCase):
    """Every workflow's python invocation is in the table, or excused in writing."""

    @classmethod
    def setUpClass(cls):
        cls.workflow_text = "\n".join(
            path.read_text(encoding="utf-8") for path in CI_WORKFLOWS
        )
        cls.run_blocks = _run_blocks(cls.workflow_text)
        cls.runner_driven = any(
            _LANE_RUNNER in {_clean(token) for token in _tokens(block)}
            for block in cls.run_blocks
        )
        cls.keys = invocation_keys(cls.run_blocks)
        cls.covered = table_keys()

    def test_the_parser_actually_found_something(self):
        """A parser that extracts nothing would make every assertion below vacuous."""
        if self.runner_driven:
            lane_blocks = [
                block for block in self.run_blocks
                if _LANE_RUNNER in {_clean(token) for token in _tokens(block)}
                and "--lane" in _tokens(block)
            ]
            self.assertGreaterEqual(len(lane_blocks), 1, self.run_blocks)
            # Lane-owned gates are validated through CI_LANES instead of being
            # duplicated in YAML; direct GitHub-only checks may still add keys.
        else:
            self.assertGreaterEqual(len(self.keys), 15, self.keys)
            self.assertIn("path:automation/store/validate_store.py", self.keys)
            self.assertIn("discover:automation/shared/tests", self.keys)
            self.assertIn("module:compileall", self.keys)

    def test_every_ci_invocation_is_covered_or_excused(self):
        excused = _excused()
        missing = [k for k in self.keys if k not in self.covered and k not in excused]
        self.assertEqual(
            missing, [],
            "GitHub workflows run these and the local gate runner does not: "
            f"{missing}. Add each to run_gates.build_gates(), or to "
            "run_gates.NOT_RUN_LOCALLY with a written reason.")

    def test_lane_runner_delegates_to_the_table_instead_of_becoming_a_leaf_gate(self):
        keys = invocation_keys([
            "python automation/gates/run_gates.py --lane ${{ matrix.lane }}"
        ])
        self.assertEqual(keys, [])

    def test_pr_body_workflow_skips_base_only_retarget_edits(self):
        workflow = (REPO_ROOT / ".github/workflows/pr-body.yml").read_text()
        self.assertIn(
            "if: github.event.action != 'edited' || "
            "github.event.changes.body != null",
            workflow,
        )

    def test_ci_classifies_against_the_pull_requests_actual_base(self):
        workflow = (REPO_ROOT / ".github/workflows/ci.yml").read_text()
        self.assertIn(
            "BASE_SHA: ${{ github.event.pull_request.base.sha }}",
            workflow,
        )
        self.assertIn('git merge-base "$BASE_SHA" "$HEAD_SHA"', workflow)
        self.assertNotIn("git merge-base origin/main", workflow)

    def test_pdf_lanes_share_one_bounded_libreoffice_install(self):
        workflow = (REPO_ROOT / ".github/workflows/ci.yml").read_text()
        self.assertEqual(workflow.count("apt-get install -y libreoffice-writer"), 1)
        self.assertIn("sudo timeout 180s sh -c", workflow)
        self.assertIn("python automation/gates/run_gates.py --lane render", workflow)
        self.assertIn("python automation/gates/run_gates.py --lane resume", workflow)

    def test_the_excuse_list_is_reasons_not_placeholders(self):
        for path, reason in run_gates.NOT_RUN_LOCALLY.items():
            self.assertGreater(len(reason), 40, f"{path}: excuse is too thin: {reason!r}")
            self.assertNotIn(reason.strip().lower(), {"n/a", "tbd", "todo"}, path)
        for name, reason in run_gates.NOT_RUN_LOCALLY_NON_PYTHON.items():
            self.assertGreater(len(reason), 40, f"{name}: excuse is too thin: {reason!r}")

    def test_the_excuse_list_carries_nothing_ci_no_longer_runs(self):
        """A stale excuse hides a gate that could now be run locally."""
        stale = [p for p in run_gates.NOT_RUN_LOCALLY if f"path:{p}" not in self.keys]
        self.assertEqual(stale, [], f"NOT_RUN_LOCALLY names paths workflows no longer "
                                    f"invokes: {stale}")

    def test_every_gate_path_exists_in_this_checkout(self):
        for gate in run_gates.build_gates(REPO_ROOT):
            for token in gate.argv:
                if "/" in token and not token.startswith("-") and token != "private/":
                    self.assertTrue((REPO_ROOT / token).exists(),
                                    f"{gate.name} names a path that does not exist: {token}")


class HookDriftTests(unittest.TestCase):
    """The pre-commit hook's python invocations are covered too."""

    @classmethod
    def setUpClass(cls):
        body = "\n".join(line for line in PRE_COMMIT.read_text(encoding="utf-8").splitlines()
                         if not line.lstrip().startswith("#"))
        cls.paths = {f"path:{_clean(t)}" for t in _tokens(body)
                     if _clean(t).endswith(".py") and "/" in _clean(t)}
        cls.covered = table_keys()

    def test_the_parser_actually_found_something(self):
        self.assertGreaterEqual(len(self.paths), 5, self.paths)
        self.assertIn("path:automation/publish/review_gate.py", self.paths)

    def test_every_hook_invocation_is_covered_or_excused(self):
        excused = _excused()
        missing = [k for k in sorted(self.paths)
                   if k not in self.covered and k not in excused]
        self.assertEqual(missing, [],
                         f"automation/hooks/pre-commit runs these and the runner does "
                         f"not: {missing}")


class TableSanityTests(unittest.TestCase):
    def setUp(self):
        self.gates = run_gates.build_gates(REPO_ROOT)

    def test_names_are_unique_kebab_case(self):
        names = [g.name for g in self.gates]
        self.assertEqual(len(names), len(set(names)), "duplicate gate name (logs collide)")
        for name in names:
            self.assertRegex(name, r"^[a-z0-9]+(-[a-z0-9]+)*$", name)

    def test_groups_are_valid_and_every_group_is_populated(self):
        groups = {g.group for g in self.gates}
        self.assertTrue(groups <= set(run_gates.GROUPS), groups)
        self.assertIn("hook", groups)
        self.assertIn("ci", groups)
        self.assertIn("both", groups)

    def test_python_gates_use_this_interpreter(self):
        """Never a literal .venv/bin/python — a worktree has no venv of its own."""
        for gate in self.gates:
            self.assertNotIn(".venv/bin/python", gate.argv, gate.name)
            self.assertIn(gate.argv[0], (sys.executable, "git"), gate.name)

    def test_every_gate_states_what_it_proves(self):
        for gate in self.gates:
            self.assertGreater(len(gate.what_it_proves), 30, gate.name)

    def test_the_example_render_declares_that_it_rewrites_tracked_files(self):
        """It regenerates non-reproducible DOCX/PDF bytes under examples/."""
        render = next(g for g in self.gates if g.name == "example-render")
        self.assertIsNotNone(render.dirties)
        self.assertIn("examples/", render.dirties)

    def test_the_hook_and_ci_forms_of_a_shared_script_are_separate_gates(self):
        names = {g.name for g in self.gates}
        self.assertIn("review-gate-staged", names)     # hook form
        self.assertIn("review-gate-verify-all", names)  # CI form

    def test_review_gate_adds_the_dedicated_pr_head_when_present(self):
        with mock.patch.dict(
            os.environ, {"JOBHUNT_REVIEW_HEAD": "abc123\n"}, clear=False
        ):
            gate = next(
                gate for gate in run_gates.build_gates(REPO_ROOT)
                if gate.name == "review-gate-verify-all"
            )
        self.assertEqual(gate.argv[-2:], ("--head", "abc123"))

    def test_review_gate_omits_the_pr_head_when_absent_or_blank(self):
        for value in (None, "  \n"):
            with self.subTest(value=value):
                with mock.patch.dict(os.environ, {}, clear=False):
                    if value is None:
                        os.environ.pop("JOBHUNT_REVIEW_HEAD", None)
                    else:
                        os.environ["JOBHUNT_REVIEW_HEAD"] = value
                    gate = next(
                        gate for gate in run_gates.build_gates(REPO_ROOT)
                        if gate.name == "review-gate-verify-all"
                    )
                self.assertNotIn("--head", gate.argv)

    def test_publish_shards_are_parallel_safe_and_cover_every_test_once(self):
        expected = {
            "tests-publish-review": (
                "automation/publish/tests/test_review_gate.py",
            ),
            "tests-publish-guard": (
                "automation/publish/tests/test_leak_guard.py",
                "automation/publish/tests/test_export_arming.py",
                "automation/publish/tests/test_skill_manifests.py",
                "automation/publish/tests/test_store_leak_guard.py",
            ),
            "tests-publish-export": (
                "automation/publish/tests/test_export_enumeration.py",
                "automation/publish/tests/test_export_destination.py",
            ),
        }
        publish_gates = {
            gate.name: gate for gate in self.gates if gate.name in expected
        }
        self.assertEqual(set(publish_gates), set(expected))
        for name, paths in expected.items():
            with self.subTest(gate=name):
                gate = publish_gates[name]
                self.assertTrue(gate.parallel_safe)
                self.assertEqual(gate.argv[:3], (sys.executable, "-m", "unittest"))
                self.assertEqual(gate.argv[3:], paths)
        covered = [path for paths in expected.values() for path in paths]
        on_disk = sorted(
            path.relative_to(REPO_ROOT).as_posix()
            for path in (REPO_ROOT / "automation/publish/tests").glob("test_*.py")
        )
        self.assertEqual(sorted(covered), on_disk)
        self.assertEqual(len(covered), len(set(covered)))


class OverlayIsolationTests(unittest.TestCase):
    """No gate may judge the private overlay's own documents.

    ``verify-links`` shipped as CI's bare invocation with no precondition, so on a
    MAINTAINER checkout — the only kind that has ``private/`` mounted — the runner
    read the overlay's markdown and reported RED on an otherwise green tree, while
    the two things it exists to mirror both refuse to: the pre-commit hook passes
    ``--no-overlay`` explicitly (its comment names this exact failure — "the branch
    becomes uncommittable on the maintainer's own machine"), and CI has no overlay
    to read, which makes the flag a no-op there. The overlay is a separate
    repository at its own commit, so judging this branch's documents against it
    compares two unrelated states.

    Overlay link coverage is not lost, it is relocated: the gardener routine
    (``automation/gardener/verify_links.py`` with no flags) is the deliberate,
    run-by-hand reader, and its output may name ``private/`` paths.
    """

    def test_no_link_gate_reads_the_mounted_overlay(self):
        gates = [g for g in run_gates.build_gates(REPO_ROOT)
                 if any(t.endswith("verify_links.py") for t in g.argv)]
        self.assertTrue(gates, "the table no longer runs verify_links.py at all")
        for gate in gates:
            with self.subTest(gate=gate.name):
                self.assertIn(
                    "--no-overlay", gate.argv,
                    f"{gate.name} judges the mounted overlay's markdown, which "
                    "neither pre-commit nor CI does — it goes RED on a green tree "
                    "in every maintainer checkout")

    def test_the_hook_it_mirrors_passes_the_same_flag(self):
        """If the hook ever stops passing it, this gate's copy is drift, not a mirror."""
        body = "\n".join(line for line in PRE_COMMIT.read_text(encoding="utf-8").splitlines()
                         if not line.lstrip().startswith("#"))
        self.assertIn("verify_links.py --require-roots --no-overlay", body)


class RepoRootTests(unittest.TestCase):
    """A worktree's .git is a FILE, not a directory; both must resolve."""

    def test_git_directory(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "checkout"
            (root / "automation/gates").mkdir(parents=True)
            (root / ".git").mkdir()
            self.assertEqual(run_gates._find_repo_root(root / "automation/gates"), root)

    def test_git_file_as_in_a_worktree(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "worktree"
            (root / "automation/gates").mkdir(parents=True)
            (root / ".git").write_text("gitdir: /elsewhere/.git/worktrees/x\n")
            self.assertEqual(run_gates._find_repo_root(root / "automation/gates"), root)

    def test_no_git_anywhere_is_a_refusal_not_a_guess(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(SystemExit):
                run_gates._find_repo_root(Path(td))


# ── synthetic gates for the execution tests ──────────────────────────────────

def _gate(name: str, code: str, **kwargs) -> run_gates.Gate:
    return run_gates.Gate(name=name, argv=(sys.executable, "-c", code),
                          what_it_proves=f"synthetic gate {name} for the runner's tests",
                          group="ci", **kwargs)


PASSING = _gate("synthetic-pass", "print('this gate is fine')")
FAILING = _gate("synthetic-fail",
                "import sys; print('line one'); sys.stderr.write('boom\\n'); sys.exit(3)")
SKIPPED = _gate("synthetic-skip", "print('never runs')",
                precondition=lambda root: "synthetic precondition: a tool is missing")
PREFLIGHT_FAILED = _gate(
    "synthetic-preflight-fail",
    "print('never runs')",
    precondition=lambda root: run_gates.PreconditionResult(
        run_gates.FAIL, "synthetic precondition: execution is forbidden"
    ),
)
MISSING_BINARY = run_gates.Gate(
    name="synthetic-missing-binary",
    argv=("jobhunt-no-such-binary-xyz",),
    what_it_proves="a gate whose executable is absent must SKIP, never PASS",
    group="ci")
DIRTY = run_gates.Gate(
    name="synthetic-dirty",
    argv=(sys.executable, "-c", "print('rewrote a tracked file')"),
    what_it_proves="a gate that rewrites tracked files must say so after it runs",
    group="ci",
    dirties="rewrites tracked artifacts; `git checkout --` them")
DIRTY_SKIPPED = run_gates.Gate(
    name="synthetic-dirty-skipped", argv=DIRTY.argv,
    what_it_proves="a gate that would rewrite tracked files, but did not run",
    group="ci", dirties=DIRTY.dirties,
    precondition=lambda root: "synthetic precondition: a tool is missing")


class ExecutionTests(unittest.TestCase):
    def _run(self, gates, **kwargs):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        log_dir = root / run_gates.LOG_DIR_REL
        results = run_gates.run_many(gates, log_dir, jobs=kwargs.get("jobs", 1),
                                     fail_fast=kwargs.get("fail_fast", False),
                                     root=root, on_done=lambda r: None)
        out = io.StringIO()
        code = run_gates.summarise(results, out, tail=kwargs.get("tail", 15), root=root)
        return results, code, out.getvalue(), log_dir

    def test_all_passing_exits_zero_and_says_all_green(self):
        results, code, text, _ = self._run([PASSING])
        self.assertEqual(code, 0, text)
        self.assertEqual(results[0].status, run_gates.PASS)
        self.assertIn("ALL GREEN (1 of 1 gates ran)", text)

    def test_one_failing_gate_makes_the_runner_exit_one(self):
        results, code, text, _ = self._run([PASSING, FAILING])
        self.assertEqual(code, 1, text)
        self.assertEqual([r.status for r in results],
                         [run_gates.PASS, run_gates.FAIL])
        self.assertEqual(results[1].exit_code, 3)
        self.assertIn("RED: synthetic-fail (1 of 2 failed)", text)
        self.assertNotIn("ALL GREEN", text)

    def test_a_failing_gates_log_tail_is_printed_inline(self):
        _, _, text, _ = self._run([FAILING], tail=15)
        self.assertIn("boom", text)
        self.assertIn("line one", text)

    def test_only_a_failure_gets_an_inline_tail(self):
        _, _, text, _ = self._run([PASSING])
        self.assertNotIn("this gate is fine", text)

    def test_a_skip_is_not_a_pass(self):
        results, code, text, _ = self._run([PASSING, SKIPPED])
        self.assertEqual([r.status for r in results],
                         [run_gates.PASS, run_gates.SKIP])
        self.assertEqual(code, 0, text)
        # The green line counts ONE gate, not two, and names what was skipped.
        self.assertIn("ALL GREEN (1 of 2 gates ran; 1 skipped: synthetic-skip)", text)
        self.assertIn("skipped (NOT passes): synthetic-skip", text)
        self.assertIn("synthetic precondition", text)

    def test_a_skip_alone_never_reports_a_passing_gate(self):
        """All-skip executed no check, so it is NO EVIDENCE — not a green run.

        This used to print ``ALL GREEN (0 gates, 1 skipped: …)`` and exit 0.
        """
        _, code, text, _ = self._run([SKIPPED])
        self.assertEqual(code, run_gates.EXIT_NO_EVIDENCE, text)
        self.assertNotIn("ALL GREEN", text)
        self.assertIn("NO EVIDENCE: 0 of 1 gates executed", text)
        self.assertIn("synthetic-skip", text)

    def test_a_precondition_failure_is_red_without_a_process_or_log(self):
        with mock.patch.object(run_gates.subprocess, "run") as process:
            results, code, text, log_dir = self._run([PREFLIGHT_FAILED])
        process.assert_not_called()
        self.assertEqual(results[0].status, run_gates.FAIL)
        self.assertEqual(results[0].exit_code, 1)
        self.assertIsNone(results[0].log_path)
        self.assertFalse((log_dir / "synthetic-preflight-fail.log").exists())
        self.assertEqual(code, 1, text)
        self.assertIn("RED: synthetic-preflight-fail", text)
        self.assertNotIn("ALL GREEN", text)

    def test_a_missing_executable_skips_with_the_reason(self):
        results, code, text, _ = self._run([MISSING_BINARY])
        self.assertEqual(results[0].status, run_gates.SKIP)
        self.assertIn("executable not found: jobhunt-no-such-binary-xyz", text)
        # It was the only gate, so this run executed nothing: NO EVIDENCE, exit 3.
        self.assertEqual(code, run_gates.EXIT_NO_EVIDENCE, text)
        self.assertNotIn("PASS", text.split("RESULT")[-1])

    def test_every_gate_that_ran_left_a_full_log(self):
        _, _, _, log_dir = self._run([PASSING, FAILING])
        for name, needle in (("synthetic-pass", "this gate is fine"),
                             ("synthetic-fail", "boom")):
            log = log_dir / f"{name}.log"
            self.assertTrue(log.is_file(), log)
            body = log.read_text(encoding="utf-8")
            self.assertIn(needle, body)
            self.assertTrue(body.startswith("$ "), "the log records the exact argv")
        self.assertFalse((log_dir / "synthetic-skip.log").exists())

    def test_wsl_windows_temp_is_replaced_for_gate_subprocesses(self):
        with mock.patch.object(
            run_gates,
            "_wsl_temp_overrides",
            return_value={"TMPDIR": "/tmp", "TMP": "/tmp", "TEMP": "/tmp"},
        ):
            _, code, _, log_dir = self._run([_gate(
                "synthetic-temp",
                "import os; print(os.environ['TMPDIR'], os.environ['TMP'], os.environ['TEMP'])",
            )])
        self.assertEqual(code, 0)
        body = (log_dir / "synthetic-temp.log").read_text(encoding="utf-8")
        self.assertIn("env TMPDIR=/tmp TMP=/tmp TEMP=/tmp", body.splitlines()[0])
        self.assertIn("/tmp /tmp /tmp", body)

    def test_a_gate_that_rewrites_tracked_files_says_so_after_running(self):
        _, code, text, _ = self._run([DIRTY])
        self.assertEqual(code, 0, text)
        self.assertIn("note: synthetic-dirty rewrites tracked artifacts", text)

    def test_a_skipped_dirtying_gate_does_not_claim_it_touched_anything(self):
        _, _, text, _ = self._run([DIRTY_SKIPPED])
        self.assertNotIn("note: synthetic-dirty-skipped", text)

    def test_a_failed_preflight_does_not_claim_it_dirtied_the_worktree(self):
        gate = run_gates.Gate(
            name="synthetic-dirty-preflight-fail",
            argv=DIRTY.argv,
            what_it_proves="a gate denied before launch cannot dirty the worktree",
            group="ci",
            dirties=DIRTY.dirties,
            precondition=PREFLIGHT_FAILED.precondition,
        )
        _, _, text, _ = self._run([gate])
        self.assertNotIn("note: synthetic-dirty-preflight-fail", text)

    def test_fail_fast_stops_and_still_exits_one(self):
        results, code, text, _ = self._run([FAILING, PASSING], fail_fast=True)
        self.assertEqual(code, 1)
        self.assertEqual([r.status for r in results],
                         [run_gates.FAIL, run_gates.NOTRUN])
        self.assertIn("not run (--fail-fast): synthetic-pass", text)


class SummaryHonestyTests(unittest.TestCase):
    """"Nothing ran" must never render, or exit, like "everything passed".

    The failure these pin actually happened: a run selected 8 of the 36 gates in
    the table, printed ``ALL GREEN (8 gates)``, exited 0, and was reported as a
    clean full suite. The green line had no denominator, the dropped lanes were
    never named, and a zero-gate run produced the same words and the same 0.
    """

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def execute(self, gates):
        return run_gates.run_many(
            gates, self.root / run_gates.LOG_DIR_REL, jobs=1, fail_fast=False,
            root=self.root, on_done=lambda result: None)

    def summarise(self, results, **kwargs):
        out = io.StringIO()
        code = run_gates.summarise(results, out, tail=15, root=self.root, **kwargs)
        return code, out.getvalue()

    # ── the regression guard ────────────────────────────────────────────────
    def test_a_zero_gate_run_is_never_all_green_and_never_exits_zero(self):
        for coverage in (None, run_gates.Coverage(total=36, selector="group: both")):
            with self.subTest(coverage=coverage):
                code, text = self.summarise([], coverage=coverage)
                self.assertNotIn("ALL GREEN", text)
                self.assertNotEqual(code, 0, text)
                self.assertEqual(code, run_gates.EXIT_NO_EVIDENCE, text)
                self.assertIn("NO EVIDENCE", text)

    def test_the_zero_gate_verdict_is_its_own_word_not_a_shade_of_green(self):
        _, nothing = self.summarise([], coverage=run_gates.Coverage(total=36))
        _, green = self.summarise(self.execute([PASSING]),
                                  coverage=run_gates.Coverage(total=36))
        verdict = lambda text: [line for line in text.splitlines()  # noqa: E731
                                if line.startswith(("ALL GREEN", "RED:",
                                                    "NO EVIDENCE", "NOT GREEN"))]
        self.assertEqual(len(verdict(nothing)), 1, nothing)
        self.assertEqual(len(verdict(green)), 1, green)
        # The two runs must not share a verdict word, nor an exit code.
        self.assertNotEqual(verdict(nothing)[0].split()[0],
                            verdict(green)[0].split()[0])

    def test_require_pass_keeps_its_louder_refusal_and_still_is_not_green(self):
        code, text = self.summarise([], require_pass=True)
        self.assertEqual(code, 1, text)
        self.assertIn("NOT GREEN", text)
        self.assertNotIn("ALL GREEN", text)

    # ── the denominator ─────────────────────────────────────────────────────
    def test_the_green_line_always_carries_the_denominator(self):
        results = self.execute([PASSING])
        code, text = self.summarise(
            results, coverage=run_gates.Coverage(
                total=36, selector="impact from: origin/main"))
        self.assertEqual(code, 0, text)
        self.assertIn("ALL GREEN (1 of 36 gates ran)", text)
        self.assertIn("coverage: 1 of 36 gates in the table executed", text)
        self.assertIn("35 not selected", text)
        self.assertIn("selector: impact from: origin/main", text)

    def test_coverage_is_printed_for_a_red_run_too(self):
        results = self.execute([PASSING, FAILING])
        code, text = self.summarise(results,
                                    coverage=run_gates.Coverage(total=36))
        self.assertEqual(code, 1, text)
        self.assertIn("coverage: 2 of 36 gates in the table executed", text)

    def test_gates_abandoned_by_fail_fast_are_counted_in_the_coverage_line(self):
        """They were selected, they did not run, and they are not skips.

        Left out of the detail, the four numbers stop summing to the denominator
        and a reader cannot tell how much of the selection actually executed.
        """
        results = run_gates.run_many(
            [FAILING, PASSING], self.root / run_gates.LOG_DIR_REL, jobs=1,
            fail_fast=True, root=self.root, on_done=lambda result: None)
        self.assertEqual([r.status for r in results],
                         [run_gates.FAIL, run_gates.NOTRUN])
        code, text = self.summarise(results,
                                    coverage=run_gates.Coverage(total=36))
        self.assertEqual(code, 1, text)
        self.assertIn("coverage: 1 of 36 gates in the table executed "
                      "(0 skipped, 34 not selected, 1 abandoned by --fail-fast",
                      text)

    def test_a_caller_cannot_report_a_denominator_below_what_it_ran(self):
        results = self.execute([PASSING])
        _, text = self.summarise(results, coverage=run_gates.Coverage(total=0))
        self.assertIn("ALL GREEN (1 of 1 gates ran)", text)

    # ── skips ───────────────────────────────────────────────────────────────
    def test_a_skip_is_excluded_from_the_ran_count_and_named(self):
        results = self.execute([PASSING, SKIPPED])
        code, text = self.summarise(results,
                                    coverage=run_gates.Coverage(total=36))
        self.assertEqual(code, 0, text)
        self.assertIn("ALL GREEN (1 of 36 gates ran; 1 skipped: synthetic-skip)",
                      text)
        self.assertIn("skipped (NOT passes): synthetic-skip", text)
        self.assertIn("coverage: 1 of 36 gates in the table executed "
                      "(1 skipped, 34 not selected", text)

    # ── narrowing ───────────────────────────────────────────────────────────
    def test_a_narrowed_run_names_the_dropped_lanes_and_why(self):
        results = self.execute([PASSING])
        _, text = self.summarise(results, coverage=run_gates.Coverage(
            total=36, selector="impact from: origin/main",
            dropped_lanes=("maintenance", "publish"),
            dropped_reason="the Git range contains no changes"))
        self.assertIn("lanes NOT run (2): maintenance, publish "
                      "— the Git range contains no changes", text)

    def test_an_unnarrowed_run_prints_no_dropped_lane_line(self):
        results = self.execute([PASSING])
        _, text = self.summarise(results, coverage=run_gates.Coverage(total=36))
        self.assertNotIn("lanes NOT run", text)


class CoverageWiringTests(unittest.TestCase):
    """``main`` must hand summarise the real denominator and the real drops."""

    def test_an_empty_selection_exits_no_evidence_through_the_real_cli(self):
        completed = subprocess.run(
            [sys.executable, str(REPO_ROOT / "automation/gates/run_gates.py"),
             "--only", "compileall", "--skip", "compileall"],
            cwd=tempfile.gettempdir(), stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, check=False)
        self.assertEqual(completed.returncode, run_gates.EXIT_NO_EVIDENCE,
                         completed.stdout)
        self.assertIn("NO EVIDENCE", completed.stdout)
        self.assertNotIn("ALL GREEN", completed.stdout)

    def test_a_real_passing_run_carries_the_whole_table_as_its_denominator(self):
        total = len(run_gates.build_gates(REPO_ROOT))
        completed = subprocess.run(
            [sys.executable, str(REPO_ROOT / "automation/gates/run_gates.py"),
             "--only", "mail-send-less"],
            cwd=tempfile.gettempdir(), stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, check=False)
        self.assertEqual(completed.returncode, 0, completed.stdout)
        self.assertIn(f"ALL GREEN (1 of {total} gates ran)", completed.stdout)
        self.assertIn(f"running 1 of {total} gates", completed.stdout)
        # The selector names the flag that narrowed the run. Without this it read
        # `group: both` on a run that checked one gate out of the whole table.
        self.assertIn("selector: group: both, --only mail-send-less",
                      completed.stdout)

    def test_a_hand_picked_lane_names_every_lane_it_did_not_run(self):
        out = io.StringIO()
        code = run_gates.main(["--list", "--lane", "publish"], out=out)
        self.assertEqual(code, 0)
        # --list stops before summarise, so assert the wiring the summary uses.
        asked = {"publish"}
        self.assertEqual(
            tuple(name for name in run_gates.CI_LANES if name not in asked),
            ("policy", "maintenance", "render", "resume", "shared", "job-search",
             "applications"),
        )


class WSLTempTests(unittest.TestCase):
    def test_detects_wsl_from_kernel_or_environment(self):
        self.assertTrue(run_gates._is_wsl(release="microsoft-standard-WSL2", environ={}))
        self.assertTrue(run_gates._is_wsl(
            release="linux", environ={"WSL_DISTRO_NAME": "Ubuntu"}))
        self.assertFalse(run_gates._is_wsl(release="linux", environ={}))

    def test_redirects_only_windows_mounted_temp(self):
        self.assertEqual(
            run_gates._wsl_temp_overrides(
                release="microsoft-standard-WSL2",
                environ={},
                temp_dir=Path("/mnt/c/Temp"),
            ),
            {"TMPDIR": "/tmp", "TMP": "/tmp", "TEMP": "/tmp"},
        )
        self.assertEqual(
            run_gates._wsl_temp_overrides(
                release="microsoft-standard-WSL2",
                environ={},
                temp_dir=Path("/tmp"),
            ),
            {},
        )
        self.assertEqual(
            run_gates._wsl_temp_overrides(
                release="linux",
                environ={},
                temp_dir=Path("/mnt/c/Temp"),
            ),
            {},
        )

class LibreOfficePreconditionTests(unittest.TestCase):
    def _environment(self, executable, access):
        return run_gates.libreoffice_env.LibreOfficeEnvironment(executable, access)

    def test_missing_binary_is_skip(self):
        environment = self._environment(
            None,
            run_gates.libreoffice_env.LaunchServicesAccess.NOT_APPLICABLE,
        )
        with mock.patch.object(
                run_gates.libreoffice_env,
                "libreoffice_environment",
                return_value=environment,
            ):
            result = run_gates._needs_libreoffice(REPO_ROOT)
        self.assertEqual(result.status, run_gates.SKIP)
        self.assertIn("soffice or libreoffice on PATH", result.reason)

    def test_known_denial_with_binary_is_fail(self):
        environment = self._environment(
            "/Applications/LibreOffice.app/Contents/MacOS/soffice",
            run_gates.libreoffice_env.LaunchServicesAccess.DENIED,
        )
        with mock.patch.object(
                run_gates.libreoffice_env,
                "libreoffice_environment",
                return_value=environment,
            ):
            result = run_gates._needs_libreoffice(REPO_ROOT)
        self.assertEqual(result.status, run_gates.FAIL)
        self.assertIn("No LibreOffice process was started", result.reason)
        self.assertIn("FAIL, not SKIP or PASS", result.reason)

    def test_known_denial_without_binary_is_still_fail_not_skip(self):
        environment = self._environment(
            None,
            run_gates.libreoffice_env.LaunchServicesAccess.DENIED,
        )
        with mock.patch.object(
                run_gates.libreoffice_env,
                "libreoffice_environment",
                return_value=environment,
            ):
            result = run_gates._needs_libreoffice(REPO_ROOT)
        self.assertEqual(result.status, run_gates.FAIL)
        self.assertIn("No LibreOffice process was started", result.reason)

    def test_known_denial_runs_no_subprocess_writes_no_log_and_is_red(self):
        environment = self._environment(
            "/Applications/LibreOffice.app/Contents/MacOS/soffice",
            run_gates.libreoffice_env.LaunchServicesAccess.DENIED,
        )
        gate = run_gates.Gate(
            name="synthetic-libreoffice-denied",
            argv=(sys.executable, "-c", "print('never runs')"),
            what_it_proves="a denied PDF gate must stop before its subprocess starts",
            group="ci",
            precondition=run_gates._needs_libreoffice,
            dirties="would rewrite tracked PDFs if it ran",
        )
        with tempfile.TemporaryDirectory() as td, mock.patch.object(
                run_gates.libreoffice_env,
                "libreoffice_environment",
                return_value=environment,
            ), mock.patch.object(run_gates.subprocess, "run") as process:
            root = Path(td)
            log_dir = root / run_gates.LOG_DIR_REL
            result = run_gates.run_gate(gate, log_dir, root)
            out = io.StringIO()
            code = run_gates.summarise([result], out, tail=15, root=root)
            self.assertFalse((log_dir / "synthetic-libreoffice-denied.log").exists())
        process.assert_not_called()
        text = out.getvalue()
        self.assertEqual(result.status, run_gates.FAIL)
        self.assertIsNone(result.log_path)
        self.assertEqual(code, 1, text)
        self.assertIn("RED: synthetic-libreoffice-denied", text)
        self.assertNotIn("ALL GREEN", text)
        self.assertNotIn("note: synthetic-libreoffice-denied", text)

    def test_allowed_or_unknown_environment_is_runnable(self):
        for access in (
            run_gates.libreoffice_env.LaunchServicesAccess.ALLOWED,
            run_gates.libreoffice_env.LaunchServicesAccess.UNKNOWN,
            run_gates.libreoffice_env.LaunchServicesAccess.NOT_APPLICABLE,
        ):
            with self.subTest(access=access), mock.patch.object(
                    run_gates.libreoffice_env,
                    "libreoffice_environment",
                    return_value=self._environment("/usr/bin/libreoffice", access),
                ):
                self.assertIsNone(run_gates._needs_libreoffice(REPO_ROOT))

    def test_jobhunt_override_cannot_bypass_denial(self):
        with mock.patch.dict(
                os.environ, {"JOBHUNT_SOFFICE": "/custom/soffice"}, clear=True), \
                mock.patch.object(
                    run_gates.libreoffice_env,
                    "find_soffice",
                    return_value="/custom/soffice",
                ), mock.patch.object(
                    run_gates.libreoffice_env,
                    "launchservices_access",
                    return_value=run_gates.libreoffice_env.LaunchServicesAccess.DENIED,
                ):
            result = run_gates._needs_libreoffice(REPO_ROOT)
        self.assertEqual(result.status, run_gates.FAIL)
        self.assertIn("JOBHUNT_SOFFICE only selects", result.reason)

    def test_listing_says_fail_here_and_not_skip_or_dirty(self):
        environment = self._environment(
            "/custom/soffice",
            run_gates.libreoffice_env.LaunchServicesAccess.DENIED,
        )
        gate = run_gates.Gate(
            name="synthetic-libreoffice",
            argv=(sys.executable, "-c", "print('never runs')"),
            what_it_proves="a PDF gate needs a usable LibreOffice environment",
            group="ci",
            precondition=run_gates._needs_libreoffice,
            dirties="would rewrite tracked PDFs if it ran",
        )
        out = io.StringIO()
        with mock.patch.object(
                run_gates.libreoffice_env,
                "libreoffice_environment",
                return_value=environment,
            ):
            run_gates.print_listing([gate], REPO_ROOT, out)
        text = out.getvalue()
        self.assertIn("FAIL HERE:", text)
        self.assertNotIn("SKIP HERE:", text)
        self.assertNotIn("DIRTIES THE WORKTREE", text)


class SelectionTests(unittest.TestCase):
    def setUp(self):
        self.gates = run_gates.build_gates(REPO_ROOT)

    def test_only_selects_exactly_those_gates(self):
        chosen = run_gates.select_gates(self.gates, only="verify-links,reconciler")
        self.assertEqual([g.name for g in chosen], ["reconciler", "verify-links"])

    def test_skip_removes_exactly_those_gates(self):
        chosen = run_gates.select_gates(self.gates, skip="tests-publish-export")
        names = [g.name for g in chosen]
        self.assertNotIn("tests-publish-export", names)
        self.assertEqual(len(names), len(self.gates) - 1)

    def test_group_hook_is_the_pre_commit_chain(self):
        names = [g.name for g in run_gates.select_gates(self.gates, group="hook")]
        self.assertIn("staged-private-paths", names)   # hook-only
        self.assertIn("vendor-drift", names)           # both
        self.assertNotIn("tests-shared", names)        # ci-only

    def test_group_ci_excludes_the_hook_only_forms(self):
        names = [g.name for g in run_gates.select_gates(self.gates, group="ci")]
        self.assertNotIn("review-gate-staged", names)
        self.assertIn("review-gate-verify-all", names)
        self.assertIn("vendor-drift", names)

    def test_only_and_skip_compose(self):
        chosen = run_gates.select_gates(self.gates, only="reconciler,verify-links",
                                        skip="verify-links")
        self.assertEqual([g.name for g in chosen], ["reconciler"])

    def test_an_unknown_name_is_an_error_not_a_silent_empty_run(self):
        with self.assertRaises(SystemExit):
            run_gates.select_gates(self.gates, only="no-such-gate")
        with self.assertRaises(SystemExit):
            run_gates.select_gates(self.gates, skip="no-such-gate")

    def test_each_ci_lane_has_exact_membership(self):
        expected = {
            "policy": [
                "vendor-drift", "mail-send-less", "compileall",
                "instruction-budget", "reconciler", "verify-links",
                "review-gate-verify-all", "leak-guard-tree",
            ],
            "maintenance": [
                "tests-reconcile", "tests-gardener", "tests-hooks",
                "tests-metrics", "tests-evals", "tests-gates",
                "tests-ci-classifier", "tests-cutover", "tests-workspace",
                "tests-github-workflow",
            ],
            "render": ["example-render"],
            "resume": ["tests-resume-writer"],
            "shared": ["tests-shared", "validate-example-store"],
            "job-search": [
                "tests-recall-audit", "tests-job-search", "filter-variants",
            ],
            "applications": [
                "tests-application-tracker", "tests-email-assistant",
                "tests-behavioral-prep",
            ],
            "publish": [
                "tests-publish-review", "tests-publish-guard",
                "tests-publish-export",
            ],
        }
        self.assertEqual(list(run_gates.CI_LANES), list(expected))
        for lane, names in expected.items():
            with self.subTest(lane=lane):
                chosen = run_gates.select_gates(self.gates, lane=lane)
                self.assertEqual([gate.name for gate in chosen], names)

    def test_lane_union_is_deduplicated_in_gate_table_order(self):
        chosen = run_gates.select_gates(
            self.gates, lane="job-search,maintenance,job-search"
        )
        expected_names = [
            gate.name for gate in self.gates
            if gate.name in {
                *run_gates.CI_LANES["job-search"],
                *run_gates.CI_LANES["maintenance"],
            }
        ]
        self.assertEqual([gate.name for gate in chosen], expected_names)
        self.assertEqual(len(chosen), len({gate.name for gate in chosen}))

    def test_all_ci_gates_belong_to_exactly_one_lane(self):
        lane_memberships = [
            gate_name
            for names in run_gates.CI_LANES.values()
            for gate_name in names
        ]
        self.assertEqual(len(lane_memberships), len(set(lane_memberships)))
        ci_gates = {
            gate.name for gate in self.gates if gate.group in ("ci", "both")
        }
        self.assertEqual(set(lane_memberships), ci_gates)
        self.assertEqual(
            run_gates.LONG_CI_LANES,
            ("maintenance", "render", "resume", "shared", "job-search",
             "applications", "publish"),
        )

    def test_the_real_classifier_advertises_exactly_these_long_lanes(self):
        """The tripwire ``impact_decision`` checks, asserted without a mock.

        ``impact_decision`` degrades EVERY ``--impact-from`` run to the full lane
        matrix when ``classifier.LANES != LONG_CI_LANES``, and it does so
        silently apart from one reason string. Adding a lane here (rather than a
        gate to an existing lane) is therefore a change that looks free and is
        not, so the real modules are compared to each other.
        """
        classifier = run_gates._load_change_classifier(REPO_ROOT)
        self.assertEqual(tuple(classifier.LANES), run_gates.LONG_CI_LANES)

    def test_cutover_tests_are_a_gate_in_maintenance_not_a_lane_of_their_own(self):
        gate = next(g for g in self.gates if g.name == "tests-cutover")
        self.assertIn("tests-cutover", run_gates.CI_LANES["maintenance"])
        self.assertNotIn("cutover", run_gates.CI_LANES)
        self.assertEqual(
            list(gate.argv[1:]),
            ["-m", "unittest", "discover", "automation/cutover/tests"])
        self.assertTrue((REPO_ROOT / "automation/cutover/tests").is_dir())

    def test_policy_is_the_exact_fast_blocking_set(self):
        self.assertEqual(
            run_gates.CI_LANES["policy"],
            (
                "vendor-drift", "mail-send-less", "compileall",
                "instruction-budget", "reconciler", "verify-links",
                "review-gate-verify-all", "leak-guard-tree",
            ),
        )

    def test_unknown_lane_is_an_error_not_a_silent_empty_run(self):
        with self.assertRaisesRegex(SystemExit, "unknown lane 'no-such-lane'"):
            run_gates.select_gates(self.gates, lane="no-such-lane")
        with self.assertRaisesRegex(SystemExit, "requires at least one lane name"):
            run_gates.select_gates(self.gates, lane=",")

    def test_repeating_lane_accumulates_instead_of_keeping_only_the_last(self):
        """``--lane a --lane b`` must run BOTH lanes.

        ``--lane`` was a plain store, so the repeated form silently discarded
        every lane but the last: a run asked for maintenance and policy, checked
        policy alone, and printed ALL GREEN. A gate runner that checks less than
        it was asked to and reports success is the failure mode it exists to
        prevent, and nothing in the output said a lane had been dropped.
        """
        parser = run_gates.build_parser()

        repeated = parser.parse_args(["--lane", "maintenance", "--lane", "policy"])
        self.assertEqual(repeated.lane, ["maintenance", "policy"])

        comma = parser.parse_args(["--lane", "maintenance,policy"])
        self.assertEqual(comma.lane, ["maintenance,policy"])

        # Both spellings must select the same gates once joined.
        self.assertEqual(
            {g.name for g in run_gates.select_gates(
                self.gates, lane=",".join(repeated.lane))},
            {g.name for g in run_gates.select_gates(
                self.gates, lane=",".join(comma.lane))},
        )

    def test_lane_rejects_ambiguous_primary_selectors(self):
        with self.assertRaisesRegex(SystemExit, "--lane cannot be combined with --only"):
            run_gates.select_gates(
                self.gates, lane="maintenance", only="tests-gates"
            )
        with self.assertRaisesRegex(SystemExit, "--lane cannot be combined with --group"):
            run_gates.select_gates(
                self.gates, lane="maintenance", group="ci"
            )

    def test_lane_and_skip_compose(self):
        chosen = run_gates.select_gates(
            self.gates, lane="job-search", skip="filter-variants"
        )
        self.assertEqual(
            [gate.name for gate in chosen],
            ["tests-recall-audit", "tests-job-search"],
        )


class _FakeChange:
    """Stand-in for the CI classifier's Change record."""

    def __init__(self, status, paths):
        self.status = status
        self.paths = paths


class ImpactSelectionTests(unittest.TestCase):
    SHA = "a" * 40

    def classify(self, *, lanes=(), full=False, reason="focused paths",
                 untracked=(), tree_lanes=(), tree_full=False,
                 tree_reason="every changed path has a focused CI owner",
                 tree_error=None):
        """Drive impact_decision against a fake git and a fake classifier.

        Three git reads now happen: the merge-base (text), the working-tree diff,
        and the untracked listing (both bytes). ``untracked`` stands in for a dirty
        working tree; ``tree_error`` makes the working-tree read itself fail.
        """
        merge_base = subprocess.CompletedProcess(
            ["git", "merge-base"], 0, self.SHA + "\n", ""
        )

        def git(args, **_kwargs):
            head = tuple(args[:2])
            if head == ("git", "merge-base"):
                return merge_base
            if head == ("git", "diff"):
                return subprocess.CompletedProcess(args, 0, b"", b"")
            if head == ("git", "ls-files"):
                if tree_error is not None:
                    return subprocess.CompletedProcess(args, 128, b"", tree_error)
                return subprocess.CompletedProcess(
                    args, 0, b"".join(name + b"\0" for name in untracked), b"")
            raise AssertionError(f"unexpected git invocation: {args}")

        classification = mock.Mock(lanes=lanes, full=full, reason=reason)
        tree_classification = mock.Mock(
            lanes=tree_lanes, full=tree_full, reason=tree_reason)
        classifier = mock.Mock(
            LANES=run_gates.LONG_CI_LANES,
            Change=_FakeChange,
            parse_name_status=mock.Mock(return_value=()),
            classify_range=mock.Mock(return_value=classification),
            classify=mock.Mock(return_value=tree_classification),
        )
        with mock.patch.object(
            run_gates.subprocess, "run", side_effect=git
        ) as git_run, mock.patch.object(
            run_gates, "_load_change_classifier", return_value=classifier
        ):
            decision = run_gates.impact_decision("origin/main", REPO_ROOT)
        return decision, git_run, classifier

    def test_narrow_impact_unions_policy_with_affected_long_lanes(self):
        decision, git_run, classifier = self.classify(lanes=("shared",))
        self.assertFalse(decision.full)
        self.assertEqual(decision.lanes, ("policy", "shared"))
        self.assertEqual(decision.merge_base, self.SHA)
        self.assertEqual(decision.uncommitted, 0)
        git_run.assert_any_call(
            ["git", "merge-base", "--", "origin/main", "HEAD"],
            cwd=REPO_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        classifier.classify_range.assert_called_once_with(REPO_ROOT, self.SHA, "HEAD")

    def test_uncommitted_work_widens_a_range_that_would_select_nothing(self):
        """The defect: a Git range is commit-to-commit, so a dirty tree read empty.

        An agent with unstaged edits ran ``--impact-from origin/main``, the range
        classified as "no changes", the runner narrowed to the policy lane, and the
        green line said nothing about the 28 gates it had dropped. The working tree
        is now classified too, and its lanes are unioned in.
        """
        decision, _, classifier = self.classify(
            lanes=(), reason="the Git range contains no changes",
            untracked=(b"automation/gates/run_gates.py",),
            tree_lanes=("maintenance",),
        )
        self.assertFalse(decision.full)
        self.assertEqual(decision.lanes, ("policy", "maintenance"))
        self.assertEqual(decision.uncommitted, 1)
        self.assertIn("1 uncommitted change(s) folded in", decision.reason)
        # The working tree went through the SAME fail-closed classifier as the range.
        self.assertEqual(len(classifier.classify.call_args.args[0]), 1)

    def test_uncommitted_work_can_only_widen_never_narrow(self):
        decision, _, _ = self.classify(
            lanes=("shared",), untracked=(b"skills/job-search/scripts/x.py",),
            tree_lanes=("job-search",),
        )
        # Unioned, then re-ordered into the canonical LONG_CI_LANES order.
        self.assertEqual(decision.lanes, ("policy", "shared", "job-search"))

    def test_an_unclassifiable_working_tree_expands_to_every_lane(self):
        decision, _, _ = self.classify(
            lanes=("shared",), untracked=(b"unowned.bin",), tree_full=True,
            tree_reason="unowned or foundational path: unowned.bin",
        )
        self.assertTrue(decision.full)
        self.assertEqual(decision.lanes, ("policy", *run_gates.LONG_CI_LANES))

    def test_an_unreadable_working_tree_expands_to_every_lane(self):
        decision, _, _ = self.classify(
            lanes=("shared",), tree_error=b"fatal: not a git repository\n")
        self.assertTrue(decision.full)
        self.assertIn("uncommitted changes could not be classified", decision.reason)
        self.assertEqual(decision.lanes, ("policy", *run_gates.LONG_CI_LANES))

    def test_a_narrowed_decision_names_the_lanes_it_dropped(self):
        decision, _, _ = self.classify(lanes=("shared",))
        self.assertEqual(
            decision.dropped_lanes,
            ("maintenance", "render", "resume", "job-search", "applications",
             "publish"),
        )
        out = io.StringIO()
        run_gates.print_impact_decision(decision, out)
        text = out.getvalue()
        self.assertIn("lanes DROPPED (6 of 8):", text)
        self.assertIn("publish", text)

    def test_a_full_decision_drops_nothing(self):
        decision, _, _ = self.classify(lanes=("shared",), full=True)
        self.assertEqual(decision.dropped_lanes, ())
        out = io.StringIO()
        run_gates.print_impact_decision(decision, out)
        self.assertNotIn("lanes DROPPED", out.getvalue())

    def test_inert_impact_selects_policy_only(self):
        decision, _, _ = self.classify(
            lanes=(), reason="all changed paths are documentation or process records"
        )
        self.assertFalse(decision.full)
        self.assertEqual(decision.lanes, ("policy",))

    def test_classifier_full_or_unknown_lane_falls_back_to_every_lane(self):
        cases = (
            (("shared",), True, "classifier requested full coverage"),
            (("unknown",), False, "ambiguous result"),
        )
        for lanes, full, reason in cases:
            with self.subTest(lanes=lanes, full=full):
                decision, _, _ = self.classify(
                    lanes=lanes, full=full, reason=reason
                )
                self.assertTrue(decision.full)
                self.assertEqual(
                    decision.lanes, ("policy", *run_gates.LONG_CI_LANES)
                )

    def test_bad_or_ambiguous_ref_falls_back_without_classifying(self):
        results = (
            subprocess.CompletedProcess([], 128, "", "bad revision\n"),
            subprocess.CompletedProcess([], 0, self.SHA + "\n" + "b" * 40, ""),
        )
        for completed in results:
            with self.subTest(returncode=completed.returncode):
                with mock.patch.object(
                    run_gates.subprocess, "run", return_value=completed
                ), mock.patch.object(
                    run_gates, "_load_change_classifier"
                ) as load_classifier:
                    decision = run_gates.impact_decision("bad-ref", REPO_ROOT)
                self.assertTrue(decision.full)
                self.assertEqual(decision.lanes, ("policy", *run_gates.LONG_CI_LANES))
                load_classifier.assert_not_called()

    def test_missing_or_broken_classifier_falls_back_to_every_lane(self):
        completed = subprocess.CompletedProcess([], 0, self.SHA + "\n", "")
        with mock.patch.object(
            run_gates.subprocess, "run", return_value=completed
        ), mock.patch.object(
            run_gates, "_load_change_classifier", side_effect=SyntaxError("broken")
        ):
            decision = run_gates.impact_decision("origin/main", REPO_ROOT)
        self.assertTrue(decision.full)
        self.assertIn("classifier unavailable", decision.reason)

    def test_impact_rejects_other_primary_selectors_before_running_git(self):
        conflicts = (
            ("--group", "ci"),
            ("--lane", "shared"),
            ("--only", "tests-shared"),
        )
        for flag, value in conflicts:
            with self.subTest(flag=flag):
                with mock.patch.object(
                    run_gates, "impact_decision",
                    side_effect=AssertionError("classification must not run"),
                ):
                    with self.assertRaisesRegex(
                        SystemExit, "--impact-from cannot be combined"
                    ):
                        run_gates.main(
                            ["--list", "--impact-from", "origin/main", flag, value],
                            out=io.StringIO(),
                        )

    def test_impact_and_skip_compose_and_print_the_decision_first(self):
        decision = run_gates.ImpactDecision(
            "origin/main", self.SHA, ("shared",), False, "focused paths"
        )
        out = io.StringIO()
        with mock.patch.object(run_gates, "impact_decision", return_value=decision):
            code = run_gates.main(
                ["--list", "--impact-from", "origin/main", "--skip", "verify-links"],
                out=out,
            )
        self.assertEqual(code, 0)
        text = out.getvalue()
        self.assertTrue(text.startswith("impact from 'origin/main'"), text[:100])
        self.assertIn("lanes: policy, shared", text.splitlines()[0])
        self.assertIn("gate table — 9 gates", text)
        self.assertNotRegex(text, r"(?m)^verify-links  \[")
        self.assertRegex(text, r"(?m)^tests-shared  \[")


class WorkingTreeImpactTests(unittest.TestCase):
    """The dirty-tree fix, against a REAL Git repository and the REAL classifier.

    ``ImpactSelectionTests`` mocks both Git and the classifier, so none of it would
    notice if ``git diff --name-status HEAD`` stopped reporting unstaged edits —
    which is precisely the read the defect turns on. This class builds a throwaway
    repository, copies the shipped classifier into it, and drives ``impact_decision``
    end to end with no ``mock`` anywhere.
    """

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.write("automation/ci/classify_changes.py",
                   (REPO_ROOT / "automation/ci/classify_changes.py")
                   .read_text(encoding="utf-8"))
        # Tracked so a later edit is a MODIFICATION, and owned by `maintenance`.
        self.write("automation/gates/run_gates.py", "# placeholder\n")
        # `local/` mirrors the real repo's scratch rule; `__pycache__/` is written
        # by importing the classifier copied in above, exactly as it is upstream.
        self.write(".gitignore", "local/\n__pycache__/\n")
        self.git("init", "-q")
        self.git("config", "user.email", "gates@example.invalid")
        self.git("config", "user.name", "Gate Tests")
        self.git("config", "commit.gpgsign", "false")
        self.git("add", "-A")
        self.git("commit", "-qm", "base")

    def write(self, relative: str, text: str) -> None:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def git(self, *args: str) -> None:
        subprocess.run(["git", *args], cwd=self.root, check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def decide(self):
        # merge-base(HEAD, HEAD) is HEAD, so the COMMITTED range is always empty —
        # the exact state ("the Git range contains no changes") that used to narrow
        # the run to the policy lane and report success over untested work.
        return run_gates.impact_decision("HEAD", self.root)

    def test_a_clean_tree_over_an_empty_range_still_narrows_to_policy(self):
        decision = self.decide()
        self.assertEqual(decision.uncommitted, 0)
        self.assertFalse(decision.full)
        self.assertEqual(decision.lanes, ("policy",))
        self.assertEqual(decision.dropped_lanes, run_gates.LONG_CI_LANES)
        out = io.StringIO()
        run_gates.print_impact_decision(decision, out)
        self.assertIn("working tree: clean", out.getvalue())

    def test_an_unstaged_edit_git_never_committed_still_selects_its_lane(self):
        self.write("automation/gates/run_gates.py", "# edited, never committed\n")
        decision = self.decide()
        self.assertEqual(decision.uncommitted, 1)
        self.assertEqual(decision.lanes, ("policy", "maintenance"))
        self.assertIn("1 uncommitted change(s) folded in", decision.reason)

    def test_a_staged_but_uncommitted_addition_selects_its_lane(self):
        self.write("skills/job-search/scripts/search.py", "print('hi')\n")
        self.git("add", "skills/job-search/scripts/search.py")
        decision = self.decide()
        self.assertEqual(decision.uncommitted, 1)
        self.assertEqual(decision.lanes, ("policy", "job-search"))

    def test_an_untracked_file_selects_its_lane_and_lanes_union(self):
        self.write("automation/gates/run_gates.py", "# edited\n")
        self.write("automation/publish/export_public.py", "print('new')\n")
        decision = self.decide()
        self.assertEqual(decision.uncommitted, 2)
        # Union of both classifications, in canonical lane order.
        self.assertEqual(decision.lanes, ("policy", "maintenance", "publish"))
        self.assertEqual(decision.dropped_lanes,
                         ("render", "resume", "shared", "job-search", "applications"))

    def test_a_gitignored_file_never_widens_the_selection(self):
        self.write("local/scratch/notes.py", "# disposable\n")
        decision = self.decide()
        self.assertEqual(decision.uncommitted, 0)
        self.assertEqual(decision.lanes, ("policy",))

    def test_an_unowned_untracked_path_expands_to_the_full_matrix(self):
        self.write("mystery.bin", "?\n")
        decision = self.decide()
        self.assertTrue(decision.full)
        self.assertEqual(decision.lanes, ("policy", *run_gates.LONG_CI_LANES))
        self.assertEqual(decision.dropped_lanes, ())

    def test_an_inert_uncommitted_edit_is_counted_but_widens_nothing(self):
        self.write("docs/handbook/command-cookbook.md", "prose\n")
        decision = self.decide()
        self.assertEqual(decision.uncommitted, 1)
        self.assertEqual(decision.lanes, ("policy",))
        self.assertIn("documentation or process records", decision.reason)

    def test_a_deletion_of_a_tracked_gate_file_selects_its_lane(self):
        (self.root / "automation/gates/run_gates.py").unlink()
        decision = self.decide()
        self.assertEqual(decision.uncommitted, 1)
        # A non-inert deletion is unsafe to narrow, so the classifier goes full.
        self.assertTrue(decision.full)


class CliTests(unittest.TestCase):
    def test_list_prints_the_table_and_exits_zero_without_running(self):
        out = io.StringIO()
        code = run_gates.main(["--list"], out=out)
        self.assertEqual(code, 0)
        text = out.getvalue()
        self.assertIn("vendor-drift", text)
        self.assertIn("proves:", text)
        self.assertIn("not run locally", text)

    def test_list_never_writes_the_venv_path_it_cannot_use(self):
        out = io.StringIO()
        run_gates.main(["--list"], out=out)
        self.assertIn("python automation/vendoring/sync_vendored.py --check",
                      out.getvalue())

    def test_list_accepts_a_lane(self):
        out = io.StringIO()
        code = run_gates.main(["--list", "--lane", "render,resume"], out=out)
        self.assertEqual(code, 0)
        text = out.getvalue()
        self.assertIn("example-render", text)
        self.assertIn("tests-resume-writer", text)
        self.assertNotIn("tests-shared", text)

    def test_the_script_runs_as_a_subprocess_from_any_cwd(self):
        """cwd resets between an agent's calls; the root comes from __file__."""
        with tempfile.TemporaryDirectory() as td:
            proc = subprocess.run(
                [sys.executable, str(REPO_ROOT / "automation/gates/run_gates.py"),
                 "--list"],
                cwd=td, capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn(f"repo root: {REPO_ROOT}", proc.stdout)


if __name__ == "__main__":
    unittest.main()
