"""Tests for the public-change review gate (``automation/publish/review_gate.py``).

Every behavioural test builds a THROWAWAY git repository in a ``tempfile`` dir and
runs the real CLI against it with ``--repo``. Nothing here touches this checkout's
history, its ``private/`` overlay, or any global git config (the helper redirects
HOME/XDG_CONFIG_HOME and pins ``GIT_CONFIG_GLOBAL``/``GIT_CONFIG_SYSTEM``, so a
user's ``core.hooksPath``, signing key, or commit template cannot leak in on either
an old or a new git).

The scenarios mirror the spec's green gate (docs/designs/workspace-restructure/review-gate.md)
plus the operational cases the spec leaves implicit:

  * a commit touching a public file FAILS, with the spec's wording          (exit 1)
  * a valid row PASSES, silently                                           (exit 0)
  * a wrong digest still FAILS                                             (exit 2)
  * a row rebased out of this history is SKIPPED and reported by name      (exit 0)
  * a ledger with NO ancestor row at all fails with a DISTINCT message     (exit 2)
  * a ledger-only commit does not re-trigger the gate                      (exit 0)
  * the gate is silent when nothing changed                                (exit 0)
  * the one-commit-lag loop converges (commit A blocked -> row for A staged
    with change B -> commit B succeeds -> next commit needs a row for B)
  * a rewritten historical row is detected
  * a shallow clone / an exported mirror are told apart, loudly

Run with:
    .venv/bin/python -m unittest discover automation/publish/tests
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

# Make the sibling modules importable (automation/publish/).
_PUBLISH_DIR = Path(__file__).resolve().parents[1]
if str(_PUBLISH_DIR) not in sys.path:
    sys.path.insert(0, str(_PUBLISH_DIR))

import review_gate  # noqa: E402

GATE = _PUBLISH_DIR / "review_gate.py"
LEDGER_REL = review_gate.LEDGER_REL

EMPTY_DIGEST16 = "e3b0c44298fc1c14"   # sha256 of an empty diff (the seed row's range)


def _git_env(home: Path | None = None) -> dict:
    """A git environment isolated from the user's own config.

    ``GIT_CONFIG_GLOBAL``/``GIT_CONFIG_SYSTEM`` only exist from git 2.32, and this
    repo is developed against 2.23 as well, so HOME/XDG_CONFIG_HOME are redirected
    too — that is what actually keeps a user's ``core.hooksPath``, signing key or
    commit template out of a throwaway repo on an older git.
    """
    env = dict(os.environ)
    if home is not None:
        env["HOME"] = str(home)
        env["XDG_CONFIG_HOME"] = str(home / ".config")
    env.update({
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_SYSTEM": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_AUTHOR_NAME": "Gate Test",
        "GIT_AUTHOR_EMAIL": "gate@example.com",
        "GIT_COMMITTER_NAME": "Gate Test",
        "GIT_COMMITTER_EMAIL": "gate@example.com",
        "GIT_TERMINAL_PROMPT": "0",
    })
    # A config-less run: no candidate config, no personal-token secret. Mirrors CI.
    env.pop("JOBHUNT_CONFIG", None)
    env.pop("JOBHUNT_PERSONAL_TOKENS", None)
    return env


class Sandbox:
    """A throwaway git repo laid out like the toolkit (ledger at its real path)."""

    def __init__(self, root: Path, home: Path | None = None):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.env = _git_env(home)
        self.git("init", "-q")
        # `git init -b main` needs git >= 2.28; symbolic-ref works everywhere.
        self.git("symbolic-ref", "HEAD", "refs/heads/main")
        self.git("config", "commit.gpgsign", "false")
        self.git("config", "user.name", "Gate Test")
        self.git("config", "user.email", "gate@example.com")

    # ── git ──────────────────────────────────────────────────────────────
    def git(self, *args: str, check: bool = True) -> subprocess.CompletedProcess:
        proc = subprocess.run(["git", *args], cwd=str(self.root), env=self.env,
                              capture_output=True, text=True)
        if check and proc.returncode != 0:
            raise AssertionError(f"git {' '.join(args)} failed:\n{proc.stderr}")
        return proc

    def write(self, rel: str, text: str) -> None:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def commit(self, message: str) -> str:
        self.git("add", "-A")
        self.git("commit", "-q", "-m", message)
        return self.git("rev-parse", "HEAD").stdout.strip()

    def short(self, rev: str = "HEAD") -> str:
        return self.git("rev-parse", "--short=8", rev).stdout.strip()

    # ── ledger ───────────────────────────────────────────────────────────
    def write_ledger(self, rows: list[dict]) -> None:
        body = ["# throwaway ledger"]
        for row in rows:
            body.append(f"- commit: {row['commit']}")
            if row.get("base") is not None:      # optional key; omitted = legacy row
                body.append(f"  base: {row['base']}")
            body.append(f"  reviewed_by: {row.get('reviewed_by', 'agent')}")
            body.append(f"  date: {row.get('date', '2026-07-29')}")
            body.append(f"  files: {row['files']}")
            body.append(f"  digest: sha256:{row['digest']}")
            body.append(f"  finding: {row.get('finding', 'none')}")
        self.write(LEDGER_REL, "\n".join(body) + "\n")

    def row_for(self, commit: str, base: str | None = None,
                record_base: bool = False) -> dict:
        """A correct row acknowledging ``commit`` over ``base..commit``.

        ``record_base`` writes that range start into the row's own ``base:`` key —
        what the gate now prints. Default off, so every pre-existing caller keeps
        producing the positional (legacy) row shape.
        """
        base = base if base is not None else commit
        digest = review_gate.range_digest(self.root, base, commit)
        files = review_gate.changed_files(self.root, base, commit)
        row = {"commit": self.short(commit), "files": len(files),
               "digest": digest[:16]}
        if record_base:
            row["base"] = self.short(base)
        return row

    # ── an honest rebase ─────────────────────────────────────────────────
    def rebase_onto(self, branch: str, base: str) -> tuple[str, str]:
        """Replay ``branch`` onto ``base`` — this is what updating a stacked PR does.

        Every replayed commit gets a NEW sha; the old one survives in the object
        store (unreachable) until it is garbage-collected or the branch is deleted
        and the repo is re-cloned. Returns (old tip, new tip).
        """
        old = self.git("rev-parse", branch).stdout.strip()
        self.git("checkout", "-q", branch)
        self.git("rebase", "-q", base)
        new = self.git("rev-parse", "HEAD").stdout.strip()
        assert old != new, "the rebase did not rewrite anything; the test is not honest"
        return old, new

    def seed(self, commit: str | None = None) -> str:
        """Seed the ledger with ``commit`` (default HEAD), like the real seed row."""
        commit = commit or self.git("rev-parse", "HEAD").stdout.strip()
        self.write_ledger([{"commit": self.short(commit), "files": 0,
                            "digest": EMPTY_DIGEST16, "finding": "seed row"}])
        return commit

    # ── the gate ─────────────────────────────────────────────────────────
    def gate(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, str(GATE), "--repo", str(self.root), *args],
                              cwd=str(self.root), env=self.env,
                              capture_output=True, text=True)


class GateTestCase(unittest.TestCase):
    """Base: one sandbox per test, with a first commit and a seeded ledger."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.home = Path(self._tmp.name) / "home"
        self.home.mkdir()
        self.repo = Sandbox(Path(self._tmp.name) / "repo", home=self.home)

    def bootstrap(self) -> str:
        """One content commit, then a commit that adds the seeded ledger."""
        self.repo.write("README.md", "public toolkit\n")
        self.repo.commit("initial")
        self.repo.seed()
        return self.repo.commit("add review ledger")


# ─────────────────────────────────────────────────────────────────────────────
# 1 / 6. The core decision: silence on no change, the spec's message on a change.
# ─────────────────────────────────────────────────────────────────────────────
class DecisionTests(GateTestCase):

    def test_gate_is_silent_when_nothing_changed(self):
        self.bootstrap()
        # The seed row names the commit BEFORE the ledger commit; the ledger commit
        # itself touches only the ledger, which is excluded -> nothing watched changed.
        proc = self.repo.gate()
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(proc.stdout, "")
        self.assertEqual(proc.stderr, "")

    def test_public_change_fails_with_the_spec_message(self):
        self.bootstrap()
        self.repo.write("docs/handbook/private-overlay.md", "a public doc\n")
        self.repo.write("AGENTS.md", "contract\n")
        head = self.repo.commit("public change")

        proc = self.repo.gate()
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        msg = proc.stderr
        self.assertIn("PUBLIC REVIEW GATE — not a test failure. Action required.", msg)
        self.assertIn("1 commit changed the published tree since the last recorded review",
                      msg)
        self.assertIn("touching 2 files:", msg)
        self.assertIn("    AGENTS.md", msg)
        self.assertIn("    docs/handbook/private-overlay.md", msg)
        self.assertIn("These files ship to a public repository.", msg)
        self.assertIn(f"-- . ':!{LEDGER_REL}'", msg)
        self.assertIn(f"Then append to {LEDGER_REL}:", msg)
        self.assertIn(f"    - commit: {self.repo.short(head)}", msg)
        self.assertIn("      reviewed_by: agent          # or: human", msg)
        self.assertIn("      files: 2", msg)
        self.assertIn("      digest: sha256:", msg)
        self.assertIn("      finding: none", msg)

    def test_failure_message_explains_the_one_commit_lag(self):
        """The message must tell the reader HOW to converge, not just that it failed."""
        self.bootstrap()
        self.repo.write("README.md", "changed\n")
        self.repo.commit("public change")

        msg = self.repo.gate().stderr
        self.assertIn("Stage that row ALONGSIDE your next change and commit once.", msg)
        self.assertIn("ledger from your WORKING TREE", msg)
        self.assertIn("A ledger-only commit is the way to close a branch", msg)

    def test_printed_row_is_the_row_that_makes_the_gate_pass(self):
        """Copy the printed row verbatim into the ledger -> the gate goes green."""
        self.bootstrap()
        self.repo.write("README.md", "changed\n")
        self.repo.commit("public change")

        printed = self.repo.gate().stderr
        block = printed.split(f"Then append to {LEDGER_REL}:\n\n", 1)[1]
        row_yaml = textwrap.dedent(
            "\n".join(line[4:] for line in block.splitlines()
                      if line.startswith("    ") or not line.strip())
        ).strip()
        ledger = self.repo.root / LEDGER_REL
        ledger.write_text(ledger.read_text() + row_yaml + "\n", encoding="utf-8")

        proc = self.repo.gate()
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(proc.stderr, "")

    def test_many_changed_files_are_truncated(self):
        self.bootstrap()
        for i in range(review_gate.MAX_LISTED_FILES + 7):
            self.repo.write(f"docs/handbook/doc{i:03d}.md", f"doc {i}\n")
        self.repo.commit("many files")

        msg = self.repo.gate().stderr
        self.assertIn(f"touching {review_gate.MAX_LISTED_FILES + 7} files:", msg)
        self.assertIn("... and 7 more", msg)


# ─────────────────────────────────────────────────────────────────────────────
# 2 / 3 / 8. Ledger validation: a valid row passes, a wrong one never does.
# ─────────────────────────────────────────────────────────────────────────────
class LedgerValidationTests(GateTestCase):

    def test_valid_row_passes(self):
        seeded_at = self.bootstrap()
        self.repo.write("README.md", "changed\n")
        head = self.repo.commit("public change")

        self.repo.write_ledger([
            {"commit": self.repo.short(seeded_at), "files": 0, "digest": EMPTY_DIGEST16},
            self.repo.row_for(head, base=seeded_at),
        ])
        proc = self.repo.gate()
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(proc.stderr, "")

    def test_wrong_digest_fails(self):
        seeded_at = self.bootstrap()
        self.repo.write("README.md", "changed\n")
        head = self.repo.commit("public change")

        row = self.repo.row_for(head, base=seeded_at)
        row["digest"] = "0" * 16          # plausible shape, wrong value
        self.repo.write_ledger([
            {"commit": self.repo.short(seeded_at), "files": 0, "digest": EMPTY_DIGEST16},
            row,
        ])
        proc = self.repo.gate()
        self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
        self.assertIn("ledger row 2 does not match the repository", proc.stderr)
        self.assertIn("digest: sha256:0000000000000000", proc.stderr)
        self.assertIn("append-only", proc.stderr)

    def test_wrong_file_count_fails(self):
        seeded_at = self.bootstrap()
        self.repo.write("README.md", "changed\n")
        head = self.repo.commit("public change")

        row = self.repo.row_for(head, base=seeded_at)
        row["files"] = row["files"] + 3
        self.repo.write_ledger([
            {"commit": self.repo.short(seeded_at), "files": 0, "digest": EMPTY_DIGEST16},
            row,
        ])
        proc = self.repo.gate()
        self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
        self.assertIn("does not match the repository", proc.stderr)
        self.assertIn("watched file(s)", proc.stderr)

    def test_rewritten_historical_row_is_detected(self):
        """Row 2 is rewritten long after the fact; --verify-all catches it."""
        seeded_at = self.bootstrap()
        rows = [{"commit": self.repo.short(seeded_at), "files": 0,
                 "digest": EMPTY_DIGEST16}]
        base = seeded_at
        for i in range(6):
            self.repo.write(f"docs/handbook/doc{i}.md", f"doc {i}\n")
            head = self.repo.commit(f"change {i}")
            rows.append(self.repo.row_for(head, base=base))
            base = head
        self.repo.write_ledger(rows)
        self.assertEqual(self.repo.gate("--verify-all").returncode, 0)

        # Now rewrite row 2's digest — outside the default tail of 5.
        rows[1]["digest"] = "f" * 16
        rows[1]["finding"] = "nothing to see here"
        self.repo.write_ledger(rows)

        tail = self.repo.gate()
        self.assertEqual(tail.returncode, 0,
                         "row 2 is outside the default tail, so a default run is expected "
                         "to miss it — CI's --verify-all is the append-only check")

        full = self.repo.gate("--verify-all")
        self.assertEqual(full.returncode, 2, full.stdout + full.stderr)
        self.assertIn("ledger row 2 does not match the repository", full.stderr)

    def test_rewritten_recent_row_is_detected_without_verify_all(self):
        seeded_at = self.bootstrap()
        rows = [{"commit": self.repo.short(seeded_at), "files": 0,
                 "digest": EMPTY_DIGEST16}]
        base = seeded_at
        for i in range(2):
            self.repo.write(f"docs/handbook/doc{i}.md", f"doc {i}\n")
            head = self.repo.commit(f"change {i}")
            rows.append(self.repo.row_for(head, base=base))
            base = head
        rows[1]["digest"] = "a" * 16
        self.repo.write_ledger(rows)

        proc = self.repo.gate()
        self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
        self.assertIn("ledger row 2 does not match the repository", proc.stderr)

    def test_missing_ledger_fails(self):
        self.bootstrap()
        (self.repo.root / LEDGER_REL).unlink()
        proc = self.repo.gate()
        self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
        self.assertIn("is missing", proc.stderr)

    def test_malformed_rows_fail(self):
        self.bootstrap()
        cases = {
            "missing required key(s): finding": "- commit: abcdef1234\n"
                                                "  reviewed_by: agent\n"
                                                "  date: 2026-07-29\n"
                                                "  files: 0\n"
                                                "  digest: sha256:" + "0" * 16 + "\n",
            "unknown key(s): reviewd_by": "- commit: abcdef1234\n"
                                          "  reviewd_by: agent\n"
                                          "  reviewed_by: agent\n"
                                          "  date: 2026-07-29\n"
                                          "  files: 0\n"
                                          "  digest: sha256:" + "0" * 16 + "\n"
                                          "  finding: none\n",
            "reviewed_by must be one of": "- commit: abcdef1234\n"
                                          "  reviewed_by: robot\n"
                                          "  date: 2026-07-29\n"
                                          "  files: 0\n"
                                          "  digest: sha256:" + "0" * 16 + "\n"
                                          "  finding: none\n",
            "date must be YYYY-MM-DD": "- commit: abcdef1234\n"
                                       "  reviewed_by: agent\n"
                                       "  date: yesterday\n"
                                       "  files: 0\n"
                                       "  digest: sha256:" + "0" * 16 + "\n"
                                       "  finding: none\n",
            "files must be a non-negative integer": "- commit: abcdef1234\n"
                                                    "  reviewed_by: agent\n"
                                                    "  date: 2026-07-29\n"
                                                    "  files: -2\n"
                                                    "  digest: sha256:" + "0" * 16 + "\n"
                                                    "  finding: none\n",
            "digest must carry": "- commit: abcdef1234\n"
                                 "  reviewed_by: agent\n"
                                 "  date: 2026-07-29\n"
                                 "  files: 0\n"
                                 "  digest: sha256:abc\n"
                                 "  finding: none\n",
            "digest must start with": "- commit: abcdef1234\n"
                                      "  reviewed_by: agent\n"
                                      "  date: 2026-07-29\n"
                                      "  files: 0\n"
                                      "  digest: " + "0" * 16 + "\n"
                                      "  finding: none\n",
            "finding is required": "- commit: abcdef1234\n"
                                   "  reviewed_by: agent\n"
                                   "  date: 2026-07-29\n"
                                   "  files: 0\n"
                                   "  digest: sha256:" + "0" * 16 + "\n"
                                   "  finding: ''\n",
            "commit must be >= 7 hex characters": "- commit: nothex!\n"
                                                  "  reviewed_by: agent\n"
                                                  "  date: 2026-07-29\n"
                                                  "  files: 0\n"
                                                  "  digest: sha256:" + "0" * 16 + "\n"
                                                  "  finding: none\n",
        }
        for needle, body in cases.items():
            with self.subTest(needle=needle):
                self.repo.write(LEDGER_REL, body)
                proc = self.repo.gate()
                self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
                self.assertIn(needle, proc.stderr)

    def test_empty_and_non_list_ledgers_fail(self):
        self.bootstrap()
        for body, needle in (("# only a comment\n", "empty"),
                             ("commit: abcdef1234\n", "must be a YAML list"),
                             ("[]\n", "no rows")):
            with self.subTest(body=body):
                self.repo.write(LEDGER_REL, body)
                proc = self.repo.gate()
                self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
                self.assertIn(needle, proc.stderr)

    def test_full_length_digest_is_accepted(self):
        """The spec prints 16 hex chars; a full sha256 must still verify."""
        seeded_at = self.bootstrap()
        self.repo.write("README.md", "changed\n")
        head = self.repo.commit("public change")
        full = review_gate.range_digest(self.repo.root, seeded_at, head)
        self.repo.write_ledger([
            {"commit": self.repo.short(seeded_at), "files": 0, "digest": EMPTY_DIGEST16},
            {"commit": self.repo.short(head), "files": 1, "digest": full},
        ])
        self.assertEqual(self.repo.gate().returncode, 0)


# ─────────────────────────────────────────────────────────────────────────────
# 4. A stale or unreachable last-ack fails loudly, not by crashing.
# ─────────────────────────────────────────────────────────────────────────────
class UnreachableAckTests(GateTestCase):

    def test_no_ancestor_row_at_all_fails_with_a_distinct_message(self):
        """EVERY row lives on an abandoned branch: the ledger describes another history.

        One off-chain row is survivable (the chain skips it). No ancestor row at all
        is not: there is no base in this history to diff from.
        """
        self.bootstrap()
        self.repo.git("checkout", "-q", "-b", "side")
        self.repo.write("docs/handbook/side.md", "side work\n")
        side_one = self.repo.commit("side change")
        self.repo.write("docs/handbook/side2.md", "more side work\n")
        side_two = self.repo.commit("more side work")
        self.repo.git("checkout", "-q", "main")

        # The ledger (working tree) names ONLY commits that are not ancestors of HEAD.
        self.repo.write_ledger([
            {"commit": self.repo.short(side_one), "files": 0, "digest": EMPTY_DIGEST16},
            {"commit": self.repo.short(side_two), "files": 1, "digest": "0" * 16},
        ])
        proc = self.repo.gate()
        self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
        self.assertIn("the ledger is out of sync with this branch", proc.stderr)
        self.assertIn("NONE of the 2 ledger rows", proc.stderr)
        self.assertIn("EXISTS here but is NOT", proc.stderr)
        self.assertIn("merge-base --is-ancestor", proc.stderr)
        self.assertIn("append-only", proc.stderr)
        # Both rows are named, not just the last one.
        self.assertIn(self.repo.short(side_one), proc.stderr)
        self.assertIn(self.repo.short(side_two), proc.stderr)
        # Distinct from every other failure mode.
        self.assertNotIn("not a test failure", proc.stderr)
        self.assertNotIn("NOT APPLICABLE", proc.stderr)
        self.assertNotIn("shallow clone", proc.stderr)

    def test_shallow_clone_says_so(self):
        self.bootstrap()
        first = self.repo.git("rev-list", "--max-parents=0", "HEAD").stdout.strip()
        for i in range(3):
            self.repo.write(f"docs/handbook/doc{i}.md", f"doc {i}\n")
            self.repo.commit(f"change {i}")
        # Point the ledger at the ROOT commit, which a depth-1 clone will not have.
        self.repo.write_ledger([{"commit": self.repo.short(first), "files": 0,
                                 "digest": EMPTY_DIGEST16}])
        self.repo.commit("ledger points at the root commit")

        shallow_dir = Path(self._tmp.name) / "shallow"
        subprocess.run(["git", "clone", "-q", "--depth=1",
                        f"file://{self.repo.root}", str(shallow_dir)],
                       env=_git_env(self.home), check=True, capture_output=True)
        proc = subprocess.run([sys.executable, str(GATE), "--repo", str(shallow_dir)],
                              env=_git_env(self.home), capture_output=True, text=True)
        self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
        self.assertIn("cannot run in a shallow clone", proc.stderr)
        self.assertIn("fetch-depth: 0", proc.stderr)

    def test_foreign_checkout_is_not_applicable_and_says_so(self):
        """An exported mirror (fresh git init) has none of the ledger's commits."""
        self.repo.write("README.md", "exported toolkit\n")
        self.repo.write_ledger([{"commit": "abc" * 10 + "d", "files": 0,
                                 "digest": EMPTY_DIGEST16},
                                {"commit": "beef" * 10, "files": 3,
                                 "digest": "1" * 16}])
        self.repo.commit("export")
        proc = self.repo.gate()
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("NOT APPLICABLE in this checkout", proc.stdout)
        self.assertIn("exported public", proc.stdout)
        self.assertEqual(proc.stderr, "")

    def test_not_a_git_repo_is_not_applicable(self):
        with tempfile.TemporaryDirectory() as td:
            proc = subprocess.run([sys.executable, str(GATE), "--repo", td],
                                  env=_git_env(Path(td)), capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertIn("NOT APPLICABLE", proc.stdout)


# ─────────────────────────────────────────────────────────────────────────────
# "NOT APPLICABLE" used to be exit 0 for ANY tree in which no row resolved. That
# is the export mirror's normal state AND a rewritten ledger's normal state, so
# the second passed on the first's licence — in pre-commit and in CI. The mirror
# is now told apart by its SHAPE, because it runs this repo's own tracked hook
# and workflow: a flag those files passed would disarm the maintainer checkout too.
# ─────────────────────────────────────────────────────────────────────────────
class NotApplicableIsConditionalTests(GateTestCase):

    def _unresolvable_ledger(self) -> None:
        """A ledger whose every row names a well-formed sha this repo lacks."""
        self.repo.write_ledger([{"commit": "abc" * 10 + "d", "files": 0,
                                 "digest": EMPTY_DIGEST16},
                                {"commit": "beef" * 10, "files": 3,
                                 "digest": "1" * 16}])

    def test_a_maintainer_shaped_tree_with_no_resolvable_row_fails(self):
        """A wholesale ledger rewrite. This is the case that used to exit 0."""
        self.repo.write("README.md", "public toolkit\n")
        for root in review_gate.EXPORT_ABSENT_ROOTS:
            self.repo.write(f"{root}/README.md", "process root\n")
        self._unresolvable_ledger()
        self.repo.commit("rewrite the ledger")
        proc = self.repo.gate()
        self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
        self.assertIn("the ledger describes a history this checkout does not have",
                      proc.stderr.lower())
        self.assertIn("APPEND-ONLY", proc.stderr)
        self.assertNotIn("NOT APPLICABLE", proc.stdout)

    def test_one_surviving_process_root_is_enough_to_fail(self):
        """Fail closed: a half-shaped tree is not the published mirror."""
        self.repo.write("README.md", "public toolkit\n")
        self.repo.write("tasks/README.md", "process root\n")
        self._unresolvable_ledger()
        self.repo.commit("rewrite the ledger")
        self.assertEqual(self.repo.gate().returncode, 2)

    def test_the_export_shape_is_still_tolerated_and_says_why(self):
        """The published mirror ships none of those roots — it must stay green."""
        self.repo.write("README.md", "exported toolkit\n")
        self.repo.write("docs/handbook/architecture.md", "shipped doc\n")
        self._unresolvable_ledger()
        self.repo.commit("export")
        proc = self.repo.gate()
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("NOT APPLICABLE in this checkout", proc.stdout)
        self.assertIn("published-export shape", proc.stdout)

    def test_the_explicit_flag_overrides_the_shape_test(self):
        self.repo.write("README.md", "public toolkit\n")
        for root in review_gate.EXPORT_ABSENT_ROOTS:
            self.repo.write(f"{root}/README.md", "process root\n")
        self._unresolvable_ledger()
        self.repo.commit("rewrite the ledger")
        proc = self.repo.gate("--allow-not-applicable")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("--allow-not-applicable was passed", proc.stdout)

    def test_a_resolvable_row_never_reaches_the_tolerance_branch(self):
        """The normal maintainer run is untouched by any of this."""
        self.bootstrap()
        for root in review_gate.EXPORT_ABSENT_ROOTS:
            self.repo.write(f"{root}/README.md", "process root\n")
        self.repo.commit("add the process roots")
        # HEAD now has an unreviewed change: exit 1 (review required), never 0 or 2.
        self.assertEqual(self.repo.gate().returncode, 1)


# ─────────────────────────────────────────────────────────────────────────────
# The rebase case: a row acknowledged before a stacked PR was updated names a sha
# that never landed. The chain is built from the ANCESTOR rows alone; the orphan is
# skipped for verification and REPORTED, never dropped.
# ─────────────────────────────────────────────────────────────────────────────
class RebasedRowTests(GateTestCase):

    def stack_with_an_orphan(self) -> dict:
        """A real rebase, not a simulation of one.

        main:  README → ledger → A → C → B'          (B' is B replayed)
        feat:                    A → B               (B is abandoned by the rebase)

        The row written for B before the merge names a commit that exists here but
        is not an ancestor of main — exactly what merging a stack bottom-up does to
        every PR above the one that landed.
        """
        seeded_at = self.bootstrap()
        self.repo.write("docs/handbook/a.md", "change A\n")
        commit_a = self.repo.commit("change A")

        self.repo.git("checkout", "-q", "-b", "feat")
        self.repo.write("docs/handbook/b.md", "change B\n")
        self.repo.commit("change B")

        # The PR below this one lands on main first.
        self.repo.git("checkout", "-q", "main")
        self.repo.write("docs/handbook/c.md", "change C\n")
        self.repo.commit("change C")

        # Updating the stacked branch replays B under a new sha, then it merges.
        old_tip, new_tip = self.repo.rebase_onto("feat", "main")
        self.repo.git("checkout", "-q", "main")
        self.repo.git("merge", "-q", "--ff-only", "feat")
        head = self.repo.git("rev-parse", "HEAD").stdout.strip()
        self.assertEqual(head, new_tip)

        return {"seed": seeded_at, "a": commit_a, "orphan": old_tip, "head": head}

    def ledger_through_a(self, s: dict) -> list[dict]:
        """Rows 1-3: the seed, a real row for A, and the orphaned row for B."""
        return [
            {"commit": self.repo.short(s["seed"]), "files": 0, "digest": EMPTY_DIGEST16},
            self.repo.row_for(s["a"], base=s["seed"]),
            {"commit": self.repo.short(s["orphan"]), "files": 1, "digest": "b" * 16,
             "finding": "reviewed on the branch, before the rebase renamed it"},
        ]

    def test_orphaned_row_is_skipped_and_a_later_row_still_covers_the_range(self):
        s = self.stack_with_an_orphan()
        rows = self.ledger_through_a(s)
        # The reconciliation row: written on the trunk, from the closest surviving
        # ancestor row (A), NOT from the orphan.
        rows.append(self.repo.row_for(s["head"], base=s["a"]))
        self.repo.write_ledger(rows)

        for args in ((), ("--verify-all",)):
            with self.subTest(args=args):
                proc = self.repo.gate(*args)
                self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
                self.assertEqual(proc.stderr, "")

    def test_a_skipped_row_is_named_in_the_output(self):
        s = self.stack_with_an_orphan()
        self.repo.write_ledger(self.ledger_through_a(s))

        proc = self.repo.gate()
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        self.assertIn("1 of 3 ledger row(s) are not part of this history", proc.stdout)
        self.assertIn(f"row 3  {self.repo.short(s['orphan'])}  "
                      "EXISTS here but is NOT an ancestor of HEAD", proc.stdout)
        self.assertIn("skipped for verification, not dropped", proc.stdout)
        self.assertIn("the ledger is append-only", proc.stdout)
        self.assertIn("rebased", proc.stdout)
        # Skipping is not failing: the exit code comes from the unreviewed work only.
        self.assertNotIn("out of sync", proc.stdout + proc.stderr)

    def test_the_report_is_also_printed_when_the_gate_passes(self):
        s = self.stack_with_an_orphan()
        rows = self.ledger_through_a(s)
        rows.append(self.repo.row_for(s["head"], base=s["a"]))
        self.repo.write_ledger(rows)
        self.repo.commit("acknowledge the range")     # ledger-only: still green

        proc = self.repo.gate("--verify-all")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn(f"row 3  {self.repo.short(s['orphan'])}", proc.stdout)

    def test_chain_uses_the_closest_surviving_ancestor_as_the_base(self):
        """The printed range/digest must be copy-pasteable HERE — so base = row A."""
        s = self.stack_with_an_orphan()
        self.repo.write_ledger(self.ledger_through_a(s))

        proc = self.repo.gate()
        msg = proc.stderr
        expected = review_gate.range_digest(self.repo.root, s["a"], s["head"])
        self.assertIn(f"git diff {self.repo.short(s['a'])}..{self.repo.short(s['head'])} "
                      f"-- . ':!{LEDGER_REL}'", msg)
        self.assertIn(f"({self.repo.short(s['a'])} → {self.repo.short(s['head'])})", msg)
        self.assertIn("touching 2 files:", msg)         # docs/handbook/b.md + docs/handbook/c.md
        self.assertIn("    docs/handbook/b.md", msg)
        self.assertIn("    docs/handbook/c.md", msg)
        self.assertIn("      files: 2", msg)
        self.assertIn(f"      digest: sha256:{expected[:16]}", msg)
        # NOT from the orphan, which is what the old chain would have used.
        self.assertNotIn(f"git diff {self.repo.short(s['orphan'])}..", msg)

    def test_a_row_computed_from_the_orphan_fails_and_names_the_real_base(self):
        s = self.stack_with_an_orphan()
        rows = self.ledger_through_a(s)
        rows.append(self.repo.row_for(s["head"], base=s["orphan"]))   # wrong base
        self.repo.write_ledger(rows)

        proc = self.repo.gate()
        self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
        self.assertIn("ledger row 4 does not match the repository", proc.stderr)
        self.assertIn(f"git diff {self.repo.short(s['a'])}..", proc.stderr)
        # The orphan is still reported rather than dropped, even on this failure.
        self.assertIn(f"row 3  {self.repo.short(s['orphan'])}", proc.stdout)

        rows[-1] = self.repo.row_for(s["head"], base=s["a"])          # right base
        self.repo.write_ledger(rows)
        self.assertEqual(self.repo.gate("--verify-all").returncode, 0)

    def test_an_unknown_object_row_is_reported_not_a_traceback(self):
        """A row naming a commit that is not an object here at all."""
        seeded_at = self.bootstrap()
        self.repo.write("README.md", "changed\n")
        head = self.repo.commit("public change")
        rows = [
            {"commit": self.repo.short(seeded_at), "files": 0, "digest": EMPTY_DIGEST16},
            {"commit": "dead" * 10, "files": 1, "digest": "c" * 16},
        ]
        self.repo.write_ledger(rows)

        proc = self.repo.gate()
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        self.assertIn("row 2  deaddeaddeaddeaddeaddeaddeaddeaddeaddead  "
                      "UNKNOWN OBJECT — not in this checkout at all", proc.stdout)
        self.assertNotIn("EXISTS here", proc.stdout)
        self.assertNotIn("Traceback", proc.stdout + proc.stderr)
        # The chain fell back to the seed, so the printed row is computable here.
        self.assertIn(f"git diff {self.repo.short(seeded_at)}..", proc.stderr)

        rows.append(self.repo.row_for(head, base=seeded_at))
        self.repo.write_ledger(rows)
        self.assertEqual(self.repo.gate("--verify-all").returncode, 0)

    def test_a_deleted_branch_reads_as_unknown_in_a_fresh_clone(self):
        """CI's actual situation: a clone carries only REACHABLE objects.

        A worktree or a local-path clone shares the object store and would still
        resolve the orphan, so this clones over ``file://`` — the transport that
        transfers reachable history only, like actions/checkout.
        """
        s = self.stack_with_an_orphan()
        rows = self.ledger_through_a(s)
        rows.append(self.repo.row_for(s["head"], base=s["a"]))
        self.repo.write_ledger(rows)
        self.repo.commit("acknowledge the range")     # ledger-only: still green
        self.repo.git("branch", "-D", "feat")         # the merge deleted the branch

        clone = Path(self._tmp.name) / "fresh"
        subprocess.run(["git", "clone", "-q", f"file://{self.repo.root}", str(clone)],
                       env=_git_env(self.home), check=True, capture_output=True)
        gone = subprocess.run(["git", "cat-file", "-e", s["orphan"]], cwd=str(clone),
                              env=_git_env(self.home), capture_output=True)
        self.assertNotEqual(gone.returncode, 0,
                            "the clone still has the orphan; this is not CI's situation")

        proc = subprocess.run([sys.executable, str(GATE), "--repo", str(clone),
                               "--verify-all"],
                              env=_git_env(self.home), capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn(f"row 3  {self.repo.short(s['orphan'])}  UNKNOWN OBJECT",
                      proc.stdout)
        self.assertEqual(proc.stderr, "")


# ─────────────────────────────────────────────────────────────────────────────
# The convergence case: two branches cut from ONE base each append rows at the end
# of the same list, so merging both CONCATENATES them and re-parents the second
# branch's first row onto the first branch's last commit. A row that records its
# own `base:` states its range instead of deriving it, so it cannot be re-parented.
# ─────────────────────────────────────────────────────────────────────────────
class ParallelBranchConvergenceTests(GateTestCase):

    def converge(self, record_base: bool) -> dict:
        """Two branches off one base, both merged into main. Real merges, real conflict.

        main:  README → ledger(S) → M1(merge A) → ack1 → M2(merge B)
        a:                     S → change A → ack A
        b:                     S → change B → ack B

        Both branches wrote their row against S. After M2 the list reads
        [seed(S), A, M1, B] — so B, appended last on its own branch, now sits AFTER
        M1 and the positional rule starts its range at M1 instead of S.
        """
        seed = self.bootstrap()

        self.repo.git("checkout", "-q", "-b", "branch-a", "main")
        self.repo.write("docs/handbook/a.md", "change A\n")
        a_change = self.repo.commit("change A")
        row_a = self.repo.row_for(a_change, base=seed, record_base=record_base)
        self.repo.write_ledger([self.seed_row(seed, record_base), row_a])
        a_tip = self.repo.commit("acknowledge change A")

        # Cut from the SAME base — this branch never sees branch-a's row.
        self.repo.git("checkout", "-q", "-b", "branch-b", "main")
        self.repo.write("docs/handbook/b.md", "change B\n")
        b_change = self.repo.commit("change B")
        row_b = self.repo.row_for(b_change, base=seed, record_base=record_base)
        self.repo.write_ledger([self.seed_row(seed, record_base), row_b])
        self.repo.commit("acknowledge change B")

        # Merge 1 lands cleanly: only branch-a touched the ledger.
        self.repo.git("checkout", "-q", "main")
        self.repo.git("merge", "-q", "--no-ff", "-m", "Merge branch A", "branch-a")
        m1 = self.repo.git("rev-parse", "HEAD").stdout.strip()
        row_m1 = self.repo.row_for(m1, base=a_tip, record_base=record_base)
        self.repo.write_ledger([self.seed_row(seed, record_base), row_a, row_m1])
        self.repo.commit("acknowledge merge A")

        # Merge 2 conflicts on the ledger. Resolving it the only sensible way —
        # keep both sides' rows — is what performs the silent re-parenting.
        merge = self.repo.git("merge", "--no-ff", "-m", "Merge branch B", "branch-b",
                              check=False)
        self.assertNotEqual(merge.returncode, 0,
                            "the ledger did not conflict; this is not the real case")
        rows = [self.seed_row(seed, record_base), row_a, row_m1, row_b]
        self.repo.write_ledger(rows)
        m2 = self.repo.commit("Merge branch B")

        return {"seed": seed, "a_change": a_change, "b_change": b_change,
                "m1": m1, "m2": m2, "rows": rows}

    def seed_row(self, seed: str, record_base: bool) -> dict:
        row = {"commit": self.repo.short(seed), "files": 0, "digest": EMPTY_DIGEST16,
               "finding": "seed row"}
        if record_base:
            row["base"] = self.repo.short(seed)      # the seed's zero-width range
        return row

    def test_bare_rows_are_re_parented_by_the_second_merge(self):
        """The defect: row 4 was reviewed over seed..B and is now read as M1..B."""
        s = self.converge(record_base=False)

        proc = self.repo.gate("--verify-all")
        self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
        self.assertIn("ledger row 4 does not match the repository", proc.stderr)
        # The range it is being held to starts at merge 1, not at the shared base.
        self.assertIn(f"git diff {self.repo.short(s['m1'])}..", proc.stderr)
        # Every row is an ancestor of HEAD, so nothing was skipped: the failure is
        # the derived range, not a rebase.
        self.assertNotIn("not part of this history", proc.stdout)

    def test_the_mismatch_message_explains_re_parenting_and_never_says_edit_the_row(self):
        self.converge(record_base=False)

        msg = self.repo.gate("--verify-all").stderr
        self.assertIn("records no `base:`", msg)
        self.assertIn("RE-PARENTED RANGE", msg)
        self.assertIn("git merge-base", msg)
        # The escape hatch that used to be here: rewriting a landed row's evidence.
        self.assertNotIn("Correct the digest", msg)
        self.assertIn("Never restate a row's evidence", msg)

    def test_rows_carrying_their_own_base_survive_the_convergence(self):
        """The fix: the same history, the same merge, with `base:` on every row."""
        s = self.converge(record_base=True)

        # Verification passes; what is left is the ordinary unreviewed merge commit.
        proc = self.repo.gate("--verify-all")
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        self.assertIn("PUBLIC REVIEW GATE — not a test failure", proc.stderr)

        # Close the trunk the normal way: one row for the merge, ledger-only commit.
        rows = s["rows"] + [self.repo.row_for(s["m2"], base=s["b_change"],
                                              record_base=True)]
        self.repo.write_ledger(rows)
        self.repo.commit("acknowledge merge B")

        for args in ((), ("--verify-all",)):
            with self.subTest(args=args):
                proc = self.repo.gate(*args)
                self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
                self.assertEqual(proc.stderr, "")

    def test_the_printed_row_carries_the_base_it_tells_you_to_diff(self):
        """The row the gate hands an agent must be re-parent-proof as printed."""
        self.bootstrap()
        self.repo.write("docs/handbook/a.md", "change A\n")
        head = self.repo.commit("public change")

        msg = self.repo.gate().stderr
        self.assertIn(f"    - commit: {self.repo.short(head)}", msg)
        # The printed `base:` IS the left side of the printed git diff — the row
        # states the range the reviewer was told to read, rather than deriving it.
        diff_line = next(line for line in msg.splitlines()
                         if line.strip().startswith("git diff "))
        base_s = diff_line.split("git diff ", 1)[1].split("..", 1)[0]
        self.assertNotEqual(base_s, self.repo.short(head))
        self.assertIn(f"      base: {base_s}", msg)
        self.assertIn(f"git diff {base_s}..{self.repo.short(head)} "
                      f"-- . ':!{LEDGER_REL}'", msg)

        # And the row it printed verifies as printed.
        rows = [self.seed_row(base_s, True),
                self.repo.row_for(head, base=base_s, record_base=True)]
        self.repo.write_ledger(rows)
        self.repo.commit("acknowledge the change")
        self.assertEqual(self.repo.gate("--verify-all").returncode, 0)

    def test_a_base_that_is_not_a_commit_here_is_named_not_guessed_around(self):
        seed = self.bootstrap()
        self.repo.write("docs/handbook/a.md", "change A\n")
        head = self.repo.commit("public change")
        row = self.repo.row_for(head, base=seed, record_base=True)
        row["base"] = "dead" * 10
        self.repo.write_ledger([self.seed_row(seed, True), row])

        proc = self.repo.gate("--verify-all")
        self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
        self.assertIn("names a base this checkout does not have", proc.stderr)
        self.assertIn("deaddeaddeaddeaddeaddeaddeaddeaddeaddead", proc.stderr)
        self.assertNotIn("Traceback", proc.stdout + proc.stderr)

    def test_base_is_optional_and_the_two_shapes_mix_in_one_ledger(self):
        """Additive: the 161 rows written before this key must keep verifying."""
        seed = self.bootstrap()
        self.repo.write("docs/handbook/a.md", "change A\n")
        a = self.repo.commit("change A")
        self.repo.write_ledger([self.seed_row(seed, False),
                                self.repo.row_for(a, base=seed)])   # legacy shape
        b = self.repo.commit("acknowledge A")

        self.repo.write("docs/handbook/b.md", "change B\n")
        c = self.repo.commit("change B")
        rows = [self.seed_row(seed, False),
                self.repo.row_for(a, base=seed),                     # legacy
                self.repo.row_for(c, base=a, record_base=True)]      # new shape
        self.repo.write_ledger(rows)
        self.repo.commit("acknowledge B")

        proc = self.repo.gate("--verify-all")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(proc.stderr, "")
        self.assertIsNotNone(b and c)

    def test_a_malformed_base_is_rejected_by_the_schema(self):
        seed = self.bootstrap()
        row = self.seed_row(seed, True)
        row["base"] = "nothex!"
        self.repo.write_ledger([row])

        proc = self.repo.gate()
        self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
        self.assertIn("base must be >= 7 hex characters", proc.stderr)


# ─────────────────────────────────────────────────────────────────────────────
# 5 / 7. The workflow: ledger-only commits terminate, and the lag loop converges.
# ─────────────────────────────────────────────────────────────────────────────
class WorkflowTests(GateTestCase):

    def _precommit(self) -> subprocess.CompletedProcess:
        """What the pre-commit hook does: run the gate BEFORE the commit is made."""
        return self.repo.gate()

    def test_ledger_only_commit_does_not_retrigger_the_gate(self):
        seeded_at = self.bootstrap()
        self.repo.write("README.md", "changed\n")
        change = self.repo.commit("public change")

        # A ledger-only commit acknowledging `change`.
        self.repo.write_ledger([
            {"commit": self.repo.short(seeded_at), "files": 0, "digest": EMPTY_DIGEST16},
            self.repo.row_for(change, base=seeded_at),
        ])
        self.assertEqual(self._precommit().returncode, 0,
                         "staging the row must let the ack commit through")
        ack = self.repo.commit("acknowledge the public change")

        # The ack commit itself touched only the ledger -> nothing new to review.
        proc = self.repo.gate()
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(proc.stderr, "")
        self.assertNotEqual(ack, change)
        # And it stays green on a second ledger-only commit.
        self.repo.write(LEDGER_REL,
                        (self.repo.root / LEDGER_REL).read_text() + "# a trailing note\n")
        self.repo.commit("ledger comment only")
        self.assertEqual(self.repo.gate().returncode, 0)

    def test_one_commit_lag_loop_converges(self):
        """commit A -> gate blocks -> row for A staged with change B -> B commits."""
        seeded_at = self.bootstrap()

        # ── commit A: allowed (nothing watched changed since the seed) ──
        self.assertEqual(self._precommit().returncode, 0)
        self.repo.write("docs/handbook/a.md", "change A\n")
        commit_a = self.repo.commit("change A")

        # ── commit B attempt 1: blocked, because A is unacknowledged ──
        blocked = self._precommit()
        self.assertEqual(blocked.returncode, 1, blocked.stdout + blocked.stderr)
        self.assertIn(f"- commit: {self.repo.short(commit_a)}", blocked.stderr)

        # ── stage the row for A ALONGSIDE change B ──
        self.repo.write("docs/handbook/b.md", "change B\n")
        self.repo.write_ledger([
            {"commit": self.repo.short(seeded_at), "files": 0, "digest": EMPTY_DIGEST16},
            self.repo.row_for(commit_a, base=seeded_at),
        ])
        self.assertEqual(self._precommit().returncode, 0,
                         "the row for A acknowledges HEAD, so commit B goes through")
        commit_b = self.repo.commit("change B + row for A")

        # ── commit C: blocked again, now asking for a row covering B ──
        again = self._precommit()
        self.assertEqual(again.returncode, 1, again.stdout + again.stderr)
        self.assertIn(f"- commit: {self.repo.short(commit_b)}", again.stderr)
        self.assertIn("docs/handbook/b.md", again.stderr)
        self.assertNotIn("docs/handbook/a.md", again.stderr)

        # ── close the branch with a ledger-only ack, as the message instructs ──
        self.repo.write_ledger([
            {"commit": self.repo.short(seeded_at), "files": 0, "digest": EMPTY_DIGEST16},
            self.repo.row_for(commit_a, base=seeded_at),
            self.repo.row_for(commit_b, base=commit_a),
        ])
        self.assertEqual(self._precommit().returncode, 0)
        self.repo.commit("acknowledge change B")
        final = self.repo.gate("--verify-all")
        self.assertEqual(final.returncode, 0, final.stdout + final.stderr)
        self.assertEqual(final.stderr, "")

    def test_one_row_may_cover_a_range_of_commits(self):
        seeded_at = self.bootstrap()
        for i in range(4):
            self.repo.write(f"docs/handbook/doc{i}.md", f"doc {i}\n")
            self.repo.commit(f"change {i}")
        head = self.repo.git("rev-parse", "HEAD").stdout.strip()

        msg = self.repo.gate().stderr
        self.assertIn("4 commits changed the published tree", msg)
        self.assertIn("touching 4 files:", msg)

        self.repo.write_ledger([
            {"commit": self.repo.short(seeded_at), "files": 0, "digest": EMPTY_DIGEST16},
            self.repo.row_for(head, base=seeded_at),
        ])
        self.assertEqual(self.repo.gate("--verify-all").returncode, 0)

    def test_head_flag_reads_the_ledger_from_that_rev(self):
        """CI evaluates a PR's own tip, not the merge commit's merged ledger."""
        seeded_at = self.bootstrap()
        self.repo.write("docs/handbook/a.md", "change A\n")
        commit_a = self.repo.commit("change A")
        self.repo.write_ledger([
            {"commit": self.repo.short(seeded_at), "files": 0, "digest": EMPTY_DIGEST16},
            self.repo.row_for(commit_a, base=seeded_at),
        ])
        tip = self.repo.commit("acknowledge change A")

        # Working tree moves on with an unacknowledged edit; --head <tip> ignores it.
        self.repo.write("docs/handbook/c.md", "uncommitted-then-committed\n")
        self.repo.commit("change C")

        self.assertEqual(self.repo.gate("--head", tip).returncode, 0)
        self.assertEqual(self.repo.gate().returncode, 1)


# ─────────────────────────────────────────────────────────────────────────────
# The advisory detector.
# ─────────────────────────────────────────────────────────────────────────────
class AdvisoryDetectorTests(GateTestCase):

    INDEX = textwrap.dedent("""\
        lambda-labs:
          display: Lambda Systems Inc.
          aliases: [Lambda Cloud]
          kind: employer
        canonical:
          display: Northwind Data Ltd.
          kind: employer
        """)

    def test_missing_index_reports_not_inspected(self):
        self.bootstrap()
        self.repo.write("docs/handbook/x.md", "some prose\n")
        self.repo.commit("public change")

        msg = self.repo.gate().stderr
        self.assertIn("private-company cross-reference: NOT INSPECTED", msg)
        self.assertIn(review_gate.COMPANY_INDEX_REL, msg)
        self.assertIn("NOT the same as 'no matches'", msg)
        self.assertNotIn("(none)", msg)

    def test_present_index_with_a_clean_diff_reports_none(self):
        self.bootstrap()
        self.repo.write(review_gate.COMPANY_INDEX_REL, self.INDEX)
        self.repo.write("docs/handbook/x.md", "ordinary prose about rendering\n")
        self.repo.commit("public change")

        msg = self.repo.gate().stderr
        self.assertIn("(advisory only):  (none)", msg)
        self.assertNotIn("NOT INSPECTED", msg)

    def test_a_new_display_name_is_hinted_and_demands_a_human_row(self):
        self.bootstrap()
        self.repo.write(review_gate.COMPANY_INDEX_REL, self.INDEX)
        self.repo.write("docs/handbook/x.md", "worked with Lambda Systems Inc. on the cluster\n")
        self.repo.commit("public change")

        msg = self.repo.gate().stderr
        self.assertIn("    Lambda Systems Inc.", msg)
        self.assertIn("reviewed_by: human          # REQUIRED", msg)
        self.assertIn("must be signed", msg)

    def test_a_slug_fragment_alone_does_not_fire(self):
        """`lambda` and `canonical` are ordinary words; only the display name fires."""
        self.bootstrap()
        self.repo.write(review_gate.COMPANY_INDEX_REL, self.INDEX)
        self.repo.write("docs/handbook/x.md", "a canonical lambda over the render path\n")
        self.repo.commit("public change")

        msg = self.repo.gate().stderr
        self.assertIn("(advisory only):  (none)", msg)

    def test_a_name_already_in_the_baseline_is_not_news(self):
        self.repo.write("README.md", "we already mention Lambda Systems Inc. here\n")
        self.repo.commit("initial")
        self.repo.seed()
        self.repo.commit("add review ledger")
        self.repo.write(review_gate.COMPANY_INDEX_REL, self.INDEX)
        self.repo.write("docs/handbook/x.md", "Lambda Systems Inc. again\n")
        self.repo.commit("public change")

        msg = self.repo.gate().stderr
        self.assertIn("(advisory only):  (none)", msg)

    def test_examples_and_the_ats_registry_are_skipped(self):
        self.bootstrap()
        self.repo.write(review_gate.COMPANY_INDEX_REL, self.INDEX)
        self.repo.write("examples/applications/x.md", "Lambda Systems Inc.\n")
        self.repo.write("skills/job-search/companies.yaml", "- name: Lambda Systems Inc.\n")
        self.repo.commit("public change")

        msg = self.repo.gate().stderr
        self.assertIn("(advisory only):  (none)", msg)

    def test_an_index_that_yields_no_names_reports_not_inspected(self):
        """A detector that found nothing to look at must not report a clean diff.

        Each shape below parses fine and produced ``[]``, which ``company_hints``
        printed as *inspected, (none)* — a clean bill of health from a detector that
        never had a name to match. That is precisely the failure the ``None`` return
        is documented to prevent, so all three now return ``None``.

        The message must NOT say the file is merely absent: here it is present.
        """
        for name, text in (
            ("empty mapping", "{}\n"),
            ("entries that are not mappings", "acme-labs: Acme Labs\n"),
            ("entries with no display", "acme-labs:\n  kind: employer\n"),
        ):
            with self.subTest(shape=name):
                self.setUp()
                self.bootstrap()
                self.repo.write(review_gate.COMPANY_INDEX_REL, text)
                self.repo.write("docs/handbook/x.md", "some prose\n")
                self.repo.commit("public change")

                self.assertIsNone(
                    review_gate.company_display_names(self.repo.root),
                    "an index yielding zero names is not an inspected index")
                msg = self.repo.gate().stderr
                self.assertIn("private-company cross-reference: NOT INSPECTED", msg)
                self.assertNotIn("(none)", msg)

    def test_detector_never_fails_the_gate_by_itself(self):
        """Hints on an ACKNOWLEDGED range do not turn a pass into a failure."""
        seeded_at = self.bootstrap()
        self.repo.write(review_gate.COMPANY_INDEX_REL, self.INDEX)
        self.repo.write("docs/handbook/x.md", "Lambda Systems Inc.\n")
        head = self.repo.commit("public change")
        self.repo.write_ledger([
            {"commit": self.repo.short(seeded_at), "files": 0, "digest": EMPTY_DIGEST16},
            self.repo.row_for(head, base=seeded_at),
        ])
        self.assertEqual(self.repo.gate().returncode, 0)


# ─────────────────────────────────────────────────────────────────────────────
# Scalar typing: a short sha is hex, and YAML is happy to mis-type hex.
# ─────────────────────────────────────────────────────────────────────────────
class ScalarTypingTests(unittest.TestCase):
    """Regression: an UNQUOTED short sha must survive YAML.

    Found by a test whose throwaway repo happened to produce the short sha
    ``65069829``. Under normal YAML that is an int, ``07123456`` is OCTAL (a
    different number), and ``12e45678`` is a float — so a correct row would be
    rejected, or compared against the wrong commit.
    """

    def _ledger(self, commit: str, files: str = "3") -> str:
        return ("- commit: " + commit + "\n"
                "  reviewed_by: agent\n"
                "  date: 2026-07-29\n"
                "  files: " + files + "\n"
                "  digest: sha256:" + "0" * 16 + "\n"
                "  finding: none\n")

    def test_all_digit_short_sha_stays_text(self):
        rows = review_gate.parse_ledger(self._ledger("65069829"))
        self.assertEqual(rows[0]["commit"], "65069829")

    def test_octal_looking_short_sha_stays_text(self):
        rows = review_gate.parse_ledger(self._ledger("07123456"))
        self.assertEqual(rows[0]["commit"], "07123456")

    def test_exponent_looking_short_sha_stays_text(self):
        rows = review_gate.parse_ledger(self._ledger("12e45678"))
        self.assertEqual(rows[0]["commit"], "12e45678")

    def test_files_is_still_typed_as_an_integer(self):
        rows = review_gate.parse_ledger(self._ledger("abcdef12", files="14"))
        self.assertEqual(rows[0]["files"], 14)
        self.assertIsInstance(rows[0]["files"], int)

    def test_quoted_values_still_work(self):
        rows = review_gate.parse_ledger(self._ledger('"65069829"'))
        self.assertEqual(rows[0]["commit"], "65069829")


# ─────────────────────────────────────────────────────────────────────────────
# The real ledger + wiring in THIS repo.
# ─────────────────────────────────────────────────────────────────────────────
class ThisRepoTests(unittest.TestCase):

    def test_tracked_ledger_parses_and_is_seeded(self):
        rows = review_gate.load_ledger(review_gate.REPO_ROOT)
        self.assertGreaterEqual(len(rows), 1)
        self.assertEqual(rows[0]["files"], 0)
        self.assertEqual(rows[0]["digest"], EMPTY_DIGEST16,
                         "the seed row's range is zero-width, so it hashes the empty diff")

    def test_ledger_comment_documents_the_seed(self):
        text = (review_gate.REPO_ROOT / LEDGER_REL).read_text(encoding="utf-8")
        self.assertIn("SEEDED, NOT RETROACTIVE", text)
        self.assertIn("APPEND-ONLY", text)

    def test_pre_commit_hook_runs_the_gate(self):
        hook = (review_gate.REPO_ROOT / "automation/hooks/pre-commit").read_text()
        self.assertIn("automation/publish/review_gate.py", hook)

    def test_ci_runs_the_gate_with_full_history(self):
        ci = (review_gate.REPO_ROOT / ".github/workflows/ci.yml").read_text()
        self.assertIn("automation/publish/review_gate.py", ci)
        self.assertIn("--verify-all", ci)
        self.assertIn("fetch-depth: 0", ci)

    def test_this_checkout_is_not_mistaken_for_the_published_export(self):
        """The maintainer tree and CI must get the STRICT branch, not the mirror's."""
        self.assertFalse(review_gate.is_published_export(review_gate.REPO_ROOT))

    def test_export_absent_roots_are_really_absent_from_the_export(self):
        """The shape test is only honest while the exporter ships none of them.

        Pinned rather than imported, for the same reason ``COMPANY_INDEX_REL`` is:
        a gate must not gain an import it can fail on. Adding one of these roots to
        ``export_public.ALLOWLIST_DIRS`` without updating ``EXPORT_ABSENT_ROOTS``
        would make the mirror fail its own CI, so this test fails first.
        """
        publish = review_gate.REPO_ROOT / "automation" / "publish"
        if str(publish) not in sys.path:
            sys.path.insert(0, str(publish))
        import export_public  # noqa: E402

        shipped = list(export_public.ALLOWLIST_DIRS) + list(export_public.ALLOWLIST_FILES)
        for root in review_gate.EXPORT_ABSENT_ROOTS:
            self.assertTrue((review_gate.REPO_ROOT / root).is_dir(),
                            f"{root} must exist in the maintainer checkout")
            self.assertFalse(
                [p for p in shipped if p == root or p.startswith(root + "/")],
                f"{root} is now exported; EXPORT_ABSENT_ROOTS is no longer a "
                f"discriminator for the published mirror",
            )

    def test_index_path_matches_the_shared_constant(self):
        """The index path is written twice; they must never drift.

        ``automation/shared/company_index.DEFAULT_REL`` is the single source; the
        gate restates it rather than importing it, because a gate that can fail on
        an import is a gate that can be disabled by an unrelated breakage. This
        test is what makes the restatement safe.
        """
        shared = review_gate.REPO_ROOT / "automation" / "shared"
        if str(shared) not in sys.path:
            sys.path.insert(0, str(shared))
        import company_index  # noqa: E402

        self.assertEqual(review_gate.COMPANY_INDEX_REL, company_index.DEFAULT_REL)

    def test_the_index_path_is_not_routed_through_the_config_accessor(self):
        """Routing it through ``config.companies_root()`` disarms the detector.

        With ``config.example.yaml`` that accessor resolves into ``examples/``, and
        ``overlay_mounted()`` returns True there — so the gate would read an EXAMPLE
        index in every public clone and print "inspected, (none)" instead of the
        NOT INSPECTED banner. The comment beside the constant records the
        measurement; this pins that the constant stayed a literal.
        """
        source = (review_gate.REPO_ROOT / "automation/publish/review_gate.py").read_text()
        # Comments are stripped first: the comment beside the constant NAMES the
        # accessor in order to warn against it, so a naive substring test would
        # fail on its own warning.
        code = [line for line in source.splitlines() if not line.lstrip().startswith("#")]
        self.assertNotIn("companies_root(", "\n".join(code))
        self.assertIn("DO NOT route this through", source)


if __name__ == "__main__":
    unittest.main()
