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
import re
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

# Make the sibling module importable (automation/gates/).
_GATES_DIR = Path(__file__).resolve().parents[1]
if str(_GATES_DIR) not in sys.path:
    sys.path.insert(0, str(_GATES_DIR))

import run_gates  # noqa: E402

REPO_ROOT = run_gates.REPO_ROOT
CI_WORKFLOW = REPO_ROOT / ".github/workflows/ci.yml"
PRE_COMMIT = REPO_ROOT / "automation/hooks/pre-commit"


# ── shell-ish extraction, stdlib only ────────────────────────────────────────
# pyyaml is in requirements.txt, but a YAML load would hand back the run: blocks as
# opaque strings anyway — the invocations still have to be tokenised out of them.
# So the parsing is done once, textually, and kept here.

_RUN_RE = re.compile(r"^(\s*)run:\s*(.*)$")
_BLOCK_SCALARS = {"|", "|-", "|+", ">", ">-", ">+"}


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
    """Every python invocation in ci.yml is in the table, or excused in writing."""

    @classmethod
    def setUpClass(cls):
        cls.keys = invocation_keys(_run_blocks(CI_WORKFLOW.read_text(encoding="utf-8")))
        cls.covered = table_keys()

    def test_the_parser_actually_found_something(self):
        """A parser that extracts nothing would make every assertion below vacuous."""
        self.assertGreaterEqual(len(self.keys), 15, self.keys)
        self.assertIn("path:automation/store/validate_store.py", self.keys)
        self.assertIn("discover:automation/shared/tests", self.keys)
        self.assertIn("module:compileall", self.keys)

    def test_every_ci_invocation_is_covered_or_excused(self):
        excused = _excused()
        missing = [k for k in self.keys if k not in self.covered and k not in excused]
        self.assertEqual(
            missing, [],
            "ci.yml runs these and the local gate runner does not: "
            f"{missing}. Add each to run_gates.build_gates(), or to "
            "run_gates.NOT_RUN_LOCALLY with a written reason.")

    def test_the_excuse_list_is_reasons_not_placeholders(self):
        for path, reason in run_gates.NOT_RUN_LOCALLY.items():
            self.assertGreater(len(reason), 40, f"{path}: excuse is too thin: {reason!r}")
            self.assertNotIn(reason.strip().lower(), {"n/a", "tbd", "todo"}, path)
        for name, reason in run_gates.NOT_RUN_LOCALLY_NON_PYTHON.items():
            self.assertGreater(len(reason), 40, f"{name}: excuse is too thin: {reason!r}")

    def test_the_excuse_list_carries_nothing_ci_no_longer_runs(self):
        """A stale excuse hides a gate that could now be run locally."""
        stale = [p for p in run_gates.NOT_RUN_LOCALLY if f"path:{p}" not in self.keys]
        self.assertEqual(stale, [], f"NOT_RUN_LOCALLY names paths ci.yml no longer "
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
        results = run_gates._run_many(gates, log_dir, jobs=kwargs.get("jobs", 1),
                                      fail_fast=kwargs.get("fail_fast", False),
                                      root=root, on_done=lambda r: None)
        out = io.StringIO()
        code = run_gates.summarise(results, out, tail=kwargs.get("tail", 15), root=root)
        return results, code, out.getvalue(), log_dir

    def test_all_passing_exits_zero_and_says_all_green(self):
        results, code, text, _ = self._run([PASSING])
        self.assertEqual(code, 0, text)
        self.assertEqual(results[0].status, run_gates.PASS)
        self.assertIn("ALL GREEN (1 gates)", text)

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
        self.assertIn("ALL GREEN (1 gates, 1 skipped: synthetic-skip)", text)
        self.assertIn("skipped (NOT passes): synthetic-skip", text)
        self.assertIn("synthetic precondition", text)

    def test_a_skip_alone_never_reports_a_passing_gate(self):
        _, code, text, _ = self._run([SKIPPED])
        self.assertEqual(code, 0, text)
        self.assertIn("ALL GREEN (0 gates, 1 skipped: synthetic-skip)", text)

    def test_a_missing_executable_skips_with_the_reason(self):
        results, code, text, _ = self._run([MISSING_BINARY])
        self.assertEqual(results[0].status, run_gates.SKIP)
        self.assertIn("executable not found: jobhunt-no-such-binary-xyz", text)
        self.assertEqual(code, 0, text)
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

    def test_a_gate_that_rewrites_tracked_files_says_so_after_running(self):
        _, code, text, _ = self._run([DIRTY])
        self.assertEqual(code, 0, text)
        self.assertIn("note: synthetic-dirty rewrites tracked artifacts", text)

    def test_a_skipped_dirtying_gate_does_not_claim_it_touched_anything(self):
        _, _, text, _ = self._run([DIRTY_SKIPPED])
        self.assertNotIn("note: synthetic-dirty-skipped", text)

    def test_fail_fast_stops_and_still_exits_one(self):
        results, code, text, _ = self._run([FAILING, PASSING], fail_fast=True)
        self.assertEqual(code, 1)
        self.assertEqual([r.status for r in results],
                         [run_gates.FAIL, run_gates.NOTRUN])
        self.assertIn("not run (--fail-fast): synthetic-pass", text)


class SelectionTests(unittest.TestCase):
    def setUp(self):
        self.gates = run_gates.build_gates(REPO_ROOT)

    def test_only_selects_exactly_those_gates(self):
        chosen = run_gates.select_gates(self.gates, only="verify-links,reconciler")
        self.assertEqual([g.name for g in chosen], ["reconciler", "verify-links"])

    def test_skip_removes_exactly_those_gates(self):
        chosen = run_gates.select_gates(self.gates, skip="tests-publish")
        names = [g.name for g in chosen]
        self.assertNotIn("tests-publish", names)
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
