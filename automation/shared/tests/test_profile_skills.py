"""Regression: the profile's ``## Skills`` section has exactly ONE reader.

The render-time gate (``skills/resume-writer/scripts/check.py``) and the
gardener's drift report (``automation/gardener/skill_drift.py``) each used to
carry their own section regex, and the two had drifted apart::

    check.py      r"^## Skills\\s*$(.*?)(?=^## )"          # no \\Z alternative
    skill_drift   r"^## Skills\\s*$(.*?)(?=^## |\\Z)"

A profile whose ``## Skills`` is the LAST ``##`` section — legal in a file
``AGENTS.md`` says the agent may not edit without asking — therefore parsed to
approved/weak/never = 0/0/0 in the gate while the gardener read the same bytes
fine. ``check_never_skills`` then enforced the Never BLOCKLIST against an empty
list without a word, and every skill token failed with a misleading
"uncategorized skill" message.

Fixing both regexes would only reset the fuse; the defect was that there were
two. These tests pin the single implementation AND the behaviour, and the
cross-reader test runs in a SUBPROCESS so it exercises each consumer exactly as
shipped — the gardener against the canonical module, the skill against its
vendored copy — instead of whatever this suite's ``sys.path`` happens to hold.
"""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
import unittest
from pathlib import Path

from _canonical_imports import pin_shared_modules  # noqa: E402

pin_shared_modules()

import profile_skills  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[3]

# The headline fixture: '## Skills' is the FINAL '##' section of the document.
SKILLS_LAST = textwrap.dedent("""\
    # Profile

    ## Experience

    Nothing to see here.

    ## Skills

    ### Approved (include in most resumes)

    - Programming Languages: Python, Go, SQL

    ### Weak (only with an explicit JD mention)

    - Cloud & Infra: AWS (Lambda, SQS, SNS), Kafka

    ### Never (never include)

    - Languages: Rust, Scala
    """)

# The same vocabulary with a section after it — the layout that always worked.
SKILLS_MIDDLE = SKILLS_LAST.replace(
    "## Experience\n\nNothing to see here.\n\n## Skills",
    "## Skills",
).rstrip("\n") + "\n\n## Experience\n\nNothing to see here.\n"


class SharedParserTests(unittest.TestCase):
    def test_skills_as_the_final_section_parses_non_empty(self):
        approved, weak, never = profile_skills.parse_skill_lists(SKILLS_LAST)
        self.assertEqual(approved, ["Python", "Go", "SQL"])
        self.assertEqual(weak, ["AWS (Lambda, SQS, SNS)", "Kafka"])
        # The blocklist is the one that used to empty out silently.
        self.assertEqual(never, ["Rust", "Scala"])

    def test_position_of_the_section_does_not_change_the_vocabulary(self):
        self.assertEqual(profile_skills.parse_skill_lists(SKILLS_LAST),
                         profile_skills.parse_skill_lists(SKILLS_MIDDLE))
        self.assertEqual(profile_skills.canonical_keys(SKILLS_LAST),
                         profile_skills.canonical_keys(SKILLS_MIDDLE))

    def test_an_absent_section_is_distinguishable_from_an_empty_one(self):
        """``None`` vs ``""`` is what lets a gate say NOT INSPECTED."""
        self.assertIsNone(profile_skills.skills_section("# Profile\n\nNothing.\n"))
        self.assertIsNotNone(profile_skills.skills_section("## Skills\n"))
        self.assertEqual(profile_skills.parse_skill_lists("# Profile\n"), ([], [], []))
        self.assertEqual(profile_skills.canonical_keys("# Profile\n"), set())

    def test_parenthesized_tokens_stay_whole_and_expand(self):
        keys = profile_skills.canonical_keys(SKILLS_LAST)
        for expected in ("aws (lambda, sqs, sns)", "aws", "lambda", "aws lambda", "kafka"):
            self.assertIn(expected, keys)

    def test_subsection_bullets_returns_verbatim_lines(self):
        bullets = profile_skills.subsection_bullets(SKILLS_LAST)
        self.assertEqual(bullets["Never"], ["- Languages: Rust, Scala"])
        self.assertEqual(profile_skills.subsection_bullets("# Profile\n")["Never"], [])

    def test_the_shipped_example_profile_parses(self):
        """A live canary over the tracked fake profile, not only fixtures."""
        text = (REPO_ROOT / "examples" / "profile"
                / "profile.example.md").read_text(encoding="utf-8")
        approved, weak, never = profile_skills.parse_skill_lists(text)
        self.assertTrue(approved and weak and never)
        self.assertTrue(profile_skills.canonical_keys(text))


# Imports both readers in one fresh process and reports what each derives from a
# profile whose '## Skills' is the final section. Run out-of-process on purpose:
# each consumer must resolve the parser the way IT ships (the gardener from
# automation/shared/, the skill from its scripts/_vendor/ copy), which a shared
# sys.path in this suite would mask.
_CROSS_READER_PROBE = """
import json, sys
from pathlib import Path
root = Path(sys.argv[1])
profile = Path(sys.argv[2]).read_text(encoding="utf-8")

sys.path.insert(0, str(root / "automation" / "gardener"))
import skill_drift

sys.path.insert(0, str(root / "skills" / "resume-writer" / "scripts"))
import check

approved, weak, never = check.parse_skill_lists(profile)
print(json.dumps({
    "check_counts": [len(approved), len(weak), len(never)],
    "check_never": never,
    "gardener_keys": len(skill_drift.canonical_keys(profile)),
    "check_parser_file": check.parse_skill_lists.__code__.co_filename,
    "gardener_parser_file": skill_drift.canonical_keys.__code__.co_filename,
}))
"""


class CrossReaderTests(unittest.TestCase):
    """Both consumers must agree about the same bytes — the actual defect."""

    @classmethod
    def setUpClass(cls):
        fixture = Path(__file__).resolve().parent / "_skills_last_probe.md"
        fixture.write_text(SKILLS_LAST, encoding="utf-8")
        cls.addClassCleanup(fixture.unlink)
        proc = subprocess.run(
            [sys.executable, "-c", _CROSS_READER_PROBE, str(REPO_ROOT), str(fixture)],
            capture_output=True, text=True)
        if proc.returncode != 0:
            raise AssertionError(f"cross-reader probe failed:\n{proc.stderr}")
        cls.result = json.loads(proc.stdout)

    def test_both_readers_parse_a_skills_last_profile_non_empty(self):
        self.assertEqual(self.result["check_counts"], [3, 2, 2],
                         "the render gate read an empty vocabulary from a "
                         "'## Skills'-last profile")
        self.assertEqual(self.result["check_never"], ["Rust", "Scala"],
                         "the Never BLOCKLIST came back empty — the gate would "
                         "enforce it against nothing")
        self.assertGreater(self.result["gardener_keys"], 0)

    def test_both_readers_run_the_same_parser_file(self):
        """The anti-drift pin: two copies of one rule cannot come back."""
        for key in ("check_parser_file", "gardener_parser_file"):
            with self.subTest(reader=key):
                self.assertEqual(Path(self.result[key]).name, "profile_skills.py",
                                 f"{key} is not the shared parser — a private "
                                 f"copy of the '## Skills' rule has reappeared")
        # Byte-identical copies of one file, enforced by sync_vendored.py --check.
        canonical = REPO_ROOT / "automation" / "shared" / "profile_skills.py"
        vendored = (REPO_ROOT / "skills" / "resume-writer" / "scripts"
                    / "_vendor" / "profile_skills.py")
        self.assertEqual(canonical.read_bytes(), vendored.read_bytes())

    def test_no_module_declares_its_own_skills_section_regex(self):
        """A grep-level guard: the boundary literal lives in one file only."""
        needle = "## Skills"
        offenders = []
        for path in sorted(REPO_ROOT.glob("automation/**/*.py")) + sorted(
                REPO_ROOT.glob("skills/**/*.py")):
            if path.name == "profile_skills.py" or "/tests/" in path.as_posix():
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            if f'r"^{needle}' in text or f"r'^{needle}" in text:
                offenders.append(path.relative_to(REPO_ROOT).as_posix())
        self.assertEqual(offenders, [],
                         "these modules re-declare the '## Skills' section regex "
                         "instead of importing profile_skills")


if __name__ == "__main__":
    unittest.main()
