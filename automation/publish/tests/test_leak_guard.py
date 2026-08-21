"""Fixture-based tests for the publish leak guard + allowlist exporter.

Run with:
    .venv/bin/python -m unittest discover automation/publish/tests

NOTE ON THIS FILE'S OWN CONTENT: the exporter ships ``automation/publish/`` (tests
included) and the leak guard scans it. So every "real-looking" PII fixture value
below is assembled from split string fragments (``"415" + "-826-" + "1234"``) —
the literal never appears contiguously in this source, so this test module itself
stays guard-clean while the runtime fixture files it writes still trip the guard.

That rule covers SURNAMES too, and there it is not cosmetic. A bare common
surname written contiguously here is a boundary hit for every owner who shares
it, on a tracked file they never touched — which is the very defect the boundary
rule exists to fix, reintroduced one indirection later. Nine such surnames were
spelled out below before this rule was applied to them.
``ThisModuleIsSurnameCleanTests`` re-scans this file with the guard's own matcher
and fails if one comes back.
"""
from __future__ import annotations

import contextlib
import io
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

# Make the sibling modules importable (automation/publish/).
_PUBLISH_DIR = Path(__file__).resolve().parents[1]
if str(_PUBLISH_DIR) not in sys.path:
    sys.path.insert(0, str(_PUBLISH_DIR))

import check_public  # noqa: E402
import export_public  # noqa: E402

REPO_ROOT = check_public.REPO_ROOT


def _write_tree(root: Path, files: dict) -> list[str]:
    """Write ``{relpath: str|bytes}`` under ``root``; return the sorted rel paths."""
    for rel, content in files.items():
        dest = root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            dest.write_bytes(content)
        else:
            dest.write_text(content, encoding="utf-8")
    return sorted(files)


# PII fixtures, assembled so this source stays guard-clean (see module docstring).
REAL_EMAIL = "dana.harrison" + "@" + "acme-robotics" + ".io"
EXAMPLE_EMAIL = "casey" + "@" + "example" + ".com"
REAL_PHONE = "415" + "-826-" + "1234"
FICTIONAL_PHONE = "212" + "-555-" + "0142"
REAL_HOME = "/Users/" + "danaharrison" + "/notes/resume.md"
PLACEHOLDER_HOME = "/Users/" + "you" + "/notes/resume.md"
REAL_LINKEDIN = "linkedin.com/in/" + "dana-harrison-42"
PLACEHOLDER_LINKEDIN = "linkedin.com/in/" + "jordanrivers"


class StructuralPIITests(unittest.TestCase):
    """Structural PII must be caught with ZERO identity tokens active."""

    def _scan(self, files: dict) -> dict:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            tracked = _write_tree(root, files)
            return check_public.scan(root=root, tracked=tracked, tokens=[])

    def _kinds(self, result: dict) -> set:
        return {v["kind"] for v in result["violations"]["structural_pii"]}

    def test_real_domain_email_fails_with_zero_tokens(self):
        result = self._scan({"notes.md": f"reach me at {REAL_EMAIL} anytime"})
        self.assertFalse(result["ok"])
        self.assertIn("email", self._kinds(result))

    def test_example_domain_email_passes(self):
        result = self._scan({"notes.md": f"placeholder {EXAMPLE_EMAIL} in docs"})
        self.assertTrue(result["ok"], result["violations"])

    def test_us_phone_fails(self):
        result = self._scan({"notes.md": f"call {REAL_PHONE} today"})
        self.assertFalse(result["ok"])
        self.assertIn("phone", self._kinds(result))

    def test_fictional_555_phone_passes(self):
        result = self._scan({"notes.md": f"call {FICTIONAL_PHONE} (fake)"})
        self.assertTrue(result["ok"], result["violations"])

    def test_home_path_fails(self):
        result = self._scan({"notes.md": f"see {REAL_HOME}"})
        self.assertFalse(result["ok"])
        self.assertIn("home_path", self._kinds(result))

    def test_placeholder_home_path_passes(self):
        result = self._scan({"notes.md": f"see {PLACEHOLDER_HOME}"})
        self.assertTrue(result["ok"], result["violations"])

    def test_linkedin_handle_fails(self):
        result = self._scan({"notes.md": f"profile {REAL_LINKEDIN}"})
        self.assertFalse(result["ok"])
        self.assertIn("linkedin", self._kinds(result))

    def test_placeholder_linkedin_passes(self):
        result = self._scan({"notes.md": f"profile {PLACEHOLDER_LINKEDIN}"})
        self.assertTrue(result["ok"], result["violations"])


class PathDenylistTests(unittest.TestCase):
    """Private product trees / stray binaries must fail on path alone."""

    def _scan(self, files: dict) -> dict:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            tracked = _write_tree(root, files)
            return check_public.scan(root=root, tracked=tracked, tokens=[])

    def _reasons(self, result: dict) -> list:
        return [v["reason"] for v in result["violations"]["path_denylist"]]

    def test_tracked_meta_yaml_fails(self):
        result = self._scan({"meta.yaml": "role: x\n"})
        self.assertFalse(result["ok"])
        self.assertTrue(any("meta.yaml" in r for r in self._reasons(result)))

    def test_meta_yaml_under_examples_passes(self):
        result = self._scan({"examples/app/meta.yaml": "role: x\n"})
        self.assertTrue(result["ok"], result["violations"])

    def test_applications_tree_fails(self):
        result = self._scan({"applications/foo/notes.md": "hi\n"})
        self.assertFalse(result["ok"])
        self.assertTrue(any("applications/" in r for r in self._reasons(result)))

    def test_interviews_tree_fails(self):
        result = self._scan({"interviews/foo.md": "hi\n"})
        self.assertFalse(result["ok"])

    def test_agents_inputs_tree_fails(self):
        result = self._scan({".agents/inputs/master-resume/x.md": "hi\n"})
        self.assertFalse(result["ok"])

    def test_docx_outside_examples_fails(self):
        # A minimal non-zip .docx: also exercises the fail-closed path, but the
        # path denylist alone is enough to fail it.
        result = self._scan({"reports/resume.docx": b"not a real docx"})
        self.assertFalse(result["ok"])
        self.assertTrue(any("binary-outside-examples" in r or "docx" in r
                            for r in self._reasons(result)))

    def test_templates_nonexample_fails(self):
        result = self._scan({"templates/resume/reference.docx": b"x"})
        self.assertFalse(result["ok"])

    def test_templates_markdown_schema_passes_path_check(self):
        # Root templates/ carries the tracked process-file schemas (markdown).
        reasons = check_public.find_path_denylist_violations(
            ["templates/queue/decision.md", "templates/README.md"])
        self.assertEqual(reasons, [])

    def test_templates_example_named_passes_path_check(self):
        # A real (zip) example docx would pass; here we only assert the PATH check
        # does not flag an example-named template.
        reasons = check_public.find_path_denylist_violations(
            ["templates/resume/reference.example.docx"])
        self.assertEqual(reasons, [])


class FailClosedBinaryTests(unittest.TestCase):
    def _scan(self, files: dict) -> dict:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            tracked = _write_tree(root, files)
            return check_public.scan(root=root, tracked=tracked, tokens=[])

    def test_unscannable_image_fails(self):
        result = self._scan({"docs/screenshot.png": b"\x89PNG\r\n\x1a\n not-real"})
        self.assertFalse(result["ok"])
        self.assertIn("docs/screenshot.png", result["unscanned_binaries"])

    def test_example_binary_is_exempt(self):
        # An unextractable image under examples/ is intentionally shipped.
        result = self._scan({"examples/img/shot.png": b"\x89PNG\r\n not-real"})
        self.assertTrue(result["ok"], result["violations"])


class TokenTests(unittest.TestCase):
    def test_planted_token_denied_by_guard(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            tracked = _write_tree(root, {"a.txt": "hello SuperSecretSlug world\n"})
            result = check_public.scan(root=root, tracked=tracked,
                                       tokens=["SuperSecretSlug"])
        self.assertFalse(result["ok"])
        self.assertTrue(result["violations"]["personal_token"])

    def test_planted_token_denied_by_exporter_denylist(self):
        # A file whose CONTENT trips a token must be excluded by the exporter.
        reason = export_public._deny_reason("config.example.yaml", ["Rivers"])
        self.assertIsNotNone(reason)
        self.assertTrue(reason.startswith("token"))

    def test_clean_file_not_denied_by_exporter(self):
        self.assertIsNone(
            export_public._deny_reason("config.example.yaml", ["ZZZ-absent-token"]))


# ── token matching: the MUST-STILL-CATCH regression list ─────────────────────
# Every string below is a real leak shape the guard catches, and it must STAY
# caught however the matching rule evolves. The list exists because the obvious
# fix for the guard's false positives — requiring a word boundary around every
# token — silently drops the five GLUED shapes marked below, and a leak the
# guard used to catch is the only kind of regression that cannot be undone
# after a push.
#
# The token set is DERIVED from the fictional persona by the guard's own
# ``_identity_tokens``, never hand-listed. A hand-listed set would pin the
# tokens of the day and pass forever while the derivation that actually runs in
# a maintainer checkout drifted underneath it.
FICTIONAL_CONTACT = (
    "City, ST • jordan.rivers" + "@" + "example.com"
    " • linkedin.com/in/jordanrivers • github.com/jordanrivers"
)
# A home-directory basename with nothing to do with the persona, so a case that
# must be caught by a NAME-derived token can never pass on the home token by
# accident. Patched in rather than read, so the tokens do not depend on the
# machine running the suite.
FICTIONAL_HOME = "/home/" + "nobody"

# ``(label, text)``. Labels name the leak SHAPE so a failure says which one.
MUST_STILL_CATCH = [
    ("plain full name", "Contact: Jordan Rivers"),
    ("possessive", "Jordan's resume is attached"),
    ("surname-first, comma", "Rivers, Jordan — Senior Engineer"),
    ("shouted", "JORDAN RIVERS"),
    ("hyphenated surname", "Maria Garcia-Rivers reviewed it"),
    # A dotted local part: the surname is glued to an initial by a '.'.
    ("dotted email local part", "j.rivers" + "@" + "corp.com"),
    ("full email", "jordan.rivers" + "@" + "example.com"),
    ("absolute home path", "/Users/jordan/code/x"),
    ("traceback home path", 'File "/Users/jordan/x.py", line 3'),
    ("kebab application slug",
     "applications/1_applied/acme-jordan-rivers/meta.yaml"),
    ("DOCX run split", "<w:t>Jordan</w:t><w:t>Rivers</w:t>"),
    ("query parameter", "?owner=jordan&x=1"),
    ("URL path segment", "https://example.com/u/jordan/profile"),
    # ── the five GLUED shapes a boundary-only rule would drop ──
    ("GLUED linkedin handle", "linkedin.com/in/jordanrivers"),
    ("GLUED camelCase handle in a URL", "github.com/JordanRivers"),
    ("GLUED initial+surname local part", "jrivers" + "@" + "corp.com"),
    ("GLUED slug with no separator", "applications/acme-jordanrivers/meta.yaml"),
    ("GLUED home basename", "/Users/jordanrivers/code/x"),
    # ── back to shapes any rule should get ──
    ("CamelCase filename", "JordanRivers_Resume_2026.docx"),
    ("snake_case export name", "exports/jordan_rivers_baseline.yaml"),
    ("snake_case JSON key", '{"candidate_jordan": 1}'),
    ("glued document extraction", "JordanRiversSeniorEngineer"),
]

# The subset that is a PATH, scanned by the same rule through a different code
# path (``rel_lower``), so both are pinned.
MUST_STILL_CATCH_PATHS = [
    "applications/1_applied/acme-jordan-rivers/meta.yaml",
    "applications/acme-jordanrivers/meta.yaml",
    "exports/jordan_rivers_baseline.yaml",
    "docs/JordanRivers_Resume_2026.md",
]


class _RealConfigStub:
    """A config layer resolving to a REAL (non-example) config for the persona.

    ``_identity_tokens`` returns nothing for the example config by design, so a
    stub that wants tokens has to look like a maintainer checkout: an active
    path whose bytes differ from the example's.
    """

    def __init__(self, active: Path, example: Path):
        self._active = active
        self.EXAMPLE_CONFIG = example

    def config_path(self) -> Path:
        return self._active

    @staticmethod
    def candidate_name() -> str:
        return "Jordan Rivers"

    @staticmethod
    def contact_line() -> str:
        return FICTIONAL_CONTACT


def fictional_identity_tokens() -> list[str]:
    """The identity tokens the guard itself derives for the fictional persona."""
    with tempfile.TemporaryDirectory() as td:
        active = Path(td) / "config.yaml"
        active.write_text("candidate:\n  name: a maintainer checkout\n",
                          encoding="utf-8")
        example = Path(td) / "config.example.yaml"
        example.write_text("candidate:\n  name: the shipped example\n",
                           encoding="utf-8")
        with mock.patch.object(check_public.Path, "home",
                               return_value=Path(FICTIONAL_HOME)):
            return sorted(check_public._identity_tokens(
                _RealConfigStub(active, example)))


class TokenMatchingRegressionTests(unittest.TestCase):
    """Leak shapes that are caught today and must never stop being caught."""

    @classmethod
    def setUpClass(cls):
        cls.tokens = fictional_identity_tokens()

    def _token_hits(self, files: dict) -> list:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            tracked = _write_tree(root, files)
            result = check_public.scan(root=root, tracked=tracked,
                                       tokens=self.tokens)
        # Asserted on the TOKEN category specifically: several fixtures also trip
        # the path denylist or the structural-PII scan, and a pass for the wrong
        # reason would hide exactly the regression this list exists to catch.
        return result["violations"]["personal_token"]

    def test_the_persona_tokens_are_actually_derived(self):
        # A silently empty token set would make every case below vacuous.
        self.assertIn("Jordan", self.tokens)
        self.assertIn("Rivers", self.tokens)
        self.assertIn("jordanrivers", self.tokens)

    def test_every_regression_string_is_caught_in_content(self):
        for label, text in MUST_STILL_CATCH:
            with self.subTest(shape=label):
                hits = self._token_hits({"notes.md": text + "\n"})
                self.assertTrue(
                    hits, f"leak shape '{label}' is no longer caught in CONTENT")

    def test_every_regression_path_is_caught_in_the_path_scan(self):
        for rel in MUST_STILL_CATCH_PATHS:
            with self.subTest(path=rel):
                hits = self._token_hits({rel: "placeholder\n"})
                self.assertTrue(
                    [h for h in hits if h["where"] == "path"],
                    f"path '{rel}' is no longer caught by the PATH scan")

    def test_a_clean_file_is_not_flagged(self):
        # The control: the fixture machinery itself must not manufacture hits.
        self.assertEqual(
            self._token_hits({"notes.md": "an ordinary sentence about work\n"}),
            [])


# ── token matching: the MUST-NOW-ALLOW list ──────────────────────────────────
# ``(text, surname)``. Every one of these fired under pure containment, and none
# of them is a leak: the surname sits INSIDE an ordinary word. On the real
# tracked tree these accounted for hundreds of false violations per surname —
# enough that an owner with a short, common surname could not commit at all.
#
# THE SURNAMES ARE SPLIT LITERALS, and that is load-bearing rather than style.
# Written contiguously they are bare words in a TRACKED file, so this list would
# block every owner who shares one — the same defect it exists to fix, one
# indirection later. ``ThisModuleIsSurnameCleanTests`` enforces it. The ordinary
# word on the left still contains the surname; that it no longer FIRES is the
# whole point of the boundary rule, so the left column needs no splitting.
#
# A surname that is also a PLACE name is deliberately absent here. No boundary
# rule can separate the place from the person — a first name in front of it has
# exactly the same shape — so that case belongs to the opt-in English-word
# allowance tests below instead.
MUST_NOW_ALLOW = [
    ("agreed on the plan", "R" + "eed"),
    ("they disagreed", "R" + "eed"),
    ("the buffer is freed", "R" + "eed"),
    ("matched greedily", "R" + "eed"),
    ("the run parked the job", "P" + "ark"),
    ("sparkling water", "P" + "ark"),
    ("time.sleep() blocks", "L" + "ee"),
    ("the abstraction bleeds", "L" + "ee"),
    ("raise FileExistsError", "L" + "ee"),
    ("a shallow clone", "H" + "all"),
    ("the challenge is real", "H" + "all"),
    ("making progress", "K" + "ing"),
    ("a blocking call", "K" + "ing"),
    ("cross-session context", "R" + "oss"),
    ("outward facing", "W" + "ard"),
    ("read the quickstart", "Q" + "uick"),
    ("Blacksmith patterns", "S" + "mith"),
]


class TokenMatchingFalsePositiveTests(unittest.TestCase):
    """Ordinary words that must stop being reported as an identity leak."""

    def _token_hits(self, text: str, tokens: list[str]) -> list:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            tracked = _write_tree(root, {"notes.md": text + "\n"})
            result = check_public.scan(root=root, tracked=tracked, tokens=tokens)
        return result["violations"]["personal_token"]

    def test_a_surname_inside_an_ordinary_word_is_not_a_leak(self):
        for text, token in MUST_NOW_ALLOW:
            with self.subTest(word=text, token=token):
                self.assertEqual(
                    self._token_hits(text, [token]), [],
                    f"'{token}' still fires inside {text!r}")

    def test_the_same_surname_standing_alone_is_still_a_leak(self):
        # The other half. Boundary matching narrows WHERE a token counts; it
        # must not stop the token counting.
        for _, token in MUST_NOW_ALLOW:
            with self.subTest(token=token):
                self.assertTrue(self._token_hits(f"Contact: Alex {token}", [token]))
                self.assertTrue(self._token_hits(f"alex-{token.lower()}/notes", [token]))
                self.assertTrue(self._token_hits(f"Alex{token}Resume.md", [token]))


class ThisModuleIsSurnameCleanTests(unittest.TestCase):
    """This file's OWN bytes must not block an owner who shares a fixture name.

    The second-order shape of the same defect. The boundary rule stopped
    ``making`` from flagging the three-letter surname inside it — and then this
    file, which is TRACKED and which the guard scans like anything else, spelled
    that surname out as a fixture literal and flagged the owner anyway, on a
    file they never touched. Measured before this test existed: three violations
    tree-wide for that surname, one of them here; two more surnames whose ONLY
    tracked occurrence in the whole repository was this module.

    The rule that keeps it fixed is the one the module docstring already sets
    for PII fixtures: assemble the value from split literals so the contiguous
    string never lands in the source. This test enforces it with the guard's own
    matcher rather than a hand-rolled search, so it cannot drift from the rule
    that actually runs.

    Scope is deliberately THIS FILE. The same defect still lives in tracked
    prose elsewhere in the repo (process records that name surnames while
    describing this very bug); widening the check to the whole tree is filed
    separately, because it needs edits outside the guard's own files.
    """

    # Assembled from split literals — see the class docstring. A contiguous
    # surname here would be the exact regression this test exists to catch, and
    # the test would (correctly) fail on itself.
    COMMON_SURNAMES = [
        "R" + "eed", "P" + "ark", "L" + "ee", "H" + "all", "K" + "ing",
        "R" + "oss", "W" + "ard", "Q" + "uick", "S" + "mith",
    ]

    def test_the_surname_list_is_not_vacuous(self):
        # A typo that produced empty or truncated tokens would make every
        # assertion below pass while checking nothing.
        for surname in self.COMMON_SURNAMES:
            with self.subTest(surname=surname):
                self.assertGreaterEqual(len(surname), 3)
                self.assertTrue(surname[0].isupper())

    def test_no_bare_surname_appears_in_this_tracked_source(self):
        text = Path(__file__).read_text(encoding="utf-8")
        lowered = text.lower()
        for spec in check_public.classify_tokens(self.COMMON_SURNAMES):
            with self.subTest(surname=spec.token):
                self.assertEqual(spec.mode, check_public.TOKEN_BOUNDARY)
                hits = check_public._spec_match_count(spec, text, lowered)
                self.assertEqual(
                    hits, 0,
                    f"{spec.token!r} appears as a bare word in this tracked "
                    f"file ({hits} occurrence(s)); an owner with that surname "
                    "cannot commit. Assemble it from split literals instead "
                    "(see this class's docstring).")


class TokenClassificationTests(unittest.TestCase):
    """Which rule a token gets, and why. The hinge of the whole change."""

    def _mode(self, token: str, tokens=None, forced=None) -> str:
        specs = check_public.classify_tokens(tokens or [token],
                                             force_substring=forced)
        return next(s.mode for s in specs if s.token == token)

    def test_a_bare_name_part_is_boundary_matched(self):
        self.assertEqual(self._mode("Rivers"), check_public.TOKEN_BOUNDARY)

    def test_anything_carrying_punctuation_keeps_containment(self):
        for token in ("jordan.rivers" + "@" + "example.com", "jordan.rivers",
                      "field-notes", "jordan_rivers"):
            with self.subTest(token=token):
                self.assertEqual(self._mode(token), check_public.TOKEN_SUBSTRING)

    def test_a_handle_with_a_digit_keeps_containment(self):
        self.assertEqual(self._mode("jrivers7"), check_public.TOKEN_SUBSTRING)

    def test_a_compound_of_two_tokens_keeps_containment(self):
        # THE property that lets the boundary rule be safe, and the one that has
        # to survive a flat round trip through $JOBHUNT_PERSONAL_TOKENS: no
        # provenance is supplied here, only the token set.
        flat = ["Jordan", "Rivers", "jordanrivers", "jrivers"]
        self.assertEqual(self._mode("jordanrivers", flat),
                         check_public.TOKEN_SUBSTRING)
        self.assertEqual(self._mode("jrivers", flat),
                         check_public.TOKEN_SUBSTRING)
        self.assertEqual(self._mode("Jordan", flat), check_public.TOKEN_BOUNDARY)

    def test_declared_provenance_overrides_shape(self):
        # A one-word linkedin handle or home basename is a bare word by shape;
        # its provenance is what keeps it on containment.
        self.assertEqual(self._mode("riverside", forced={"riverside"}),
                         check_public.TOKEN_SUBSTRING)

    def test_an_empty_token_is_dropped_rather_than_matching_everything(self):
        self.assertEqual(check_public.classify_tokens(["", "   "]), [])

    def test_overlapping_occurrences_are_all_considered(self):
        # A non-overlapping scan consumes 'annA' (edges fail) and never sees
        # 'Anna' starting one character later (edges pass). The zero-width
        # lookahead in _boundary_pattern is what stops that being a miss.
        specs = check_public.classify_tokens(["Anna"])
        self.assertIsNotNone(check_public.first_token_hit(specs, "annAnna"))


class NameCompoundDerivationTests(unittest.TestCase):
    """The compounds that pay for the boundary rule must actually be derived."""

    @classmethod
    def setUpClass(cls):
        cls.tokens = set(fictional_identity_tokens())

    def test_glued_and_joined_forms_are_derived(self):
        for compound in ("jordanrivers", "riversjordan", "jrivers", "jordanr",
                         "jordan rivers", "jordan-rivers", "jordan_rivers"):
            with self.subTest(compound=compound):
                self.assertIn(compound, self.tokens)

    def test_compounds_are_high_specificity(self):
        with mock.patch.object(check_public, "_load_shared_config",
                               return_value=_ExampleConfigStub):
            # The example persona contributes nothing at all — the gate that
            # keeps a public clone from arming on the fictional identity.
            self.assertEqual(check_public.high_specificity_tokens(), set())
        self.assertIn("jordanrivers", check_public._name_compounds(
            ["Jordan", "Rivers"]))

    def test_a_short_pairing_is_not_shipped_as_a_compound(self):
        # 'liwu' would start hitting inside base64 and hex runs — a new class of
        # false positive is not a fix for the old one.
        self.assertEqual(check_public._name_compounds(["Li", "Wu"]), set())


# Surnames that are ALSO an ordinary English word or a place name — the case
# boundaries cannot fix. Split literals, for the reason MUST_NOW_ALLOW gives.
PLACE_SURNAME = "P" + "ark"          # 'Menlo <it>' and 'Alex <it>' are one shape
COLOR_SURNAME = "G" + "reen"
LENGTH_SURNAME = "L" + "ong"
SPEED_SURNAME = "Q" + "uick"
ROOM_SURNAME = "H" + "all"
PLACE_PREFIX = "Menlo "              # the town the place surname belongs to


class EnglishWordAllowanceTests(unittest.TestCase):
    """The opt-in allowance for a name that is ALSO an ordinary English word.

    Boundaries fix a surname hiding inside a word; they cannot fix a surname that
    IS a word — a town called 'Menlo <X>' and a person called 'Alex <X>' are the
    same string in the same shape. This is the only mechanism in the guard that
    deliberately gives up protection, so every constraint on it is pinned here:
    opt-in, loud, narrow, and still arming.
    """

    def setUp(self):
        self._saved_env = os.environ.pop(check_public.WORD_ALLOWANCE_ENV_VAR, None)

    def tearDown(self):
        os.environ.pop(check_public.WORD_ALLOWANCE_ENV_VAR, None)
        if self._saved_env is not None:
            os.environ[check_public.WORD_ALLOWANCE_ENV_VAR] = self._saved_env

    def _scan(self, text: str, tokens: list[str], allowances=None,
              forced=None) -> dict:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            tracked = _write_tree(root, {"notes.md": text + "\n"})
            return check_public.scan(root=root, tracked=tracked, tokens=tokens,
                                     allowances=allowances,
                                     force_substring=forced)

    def _hits(self, result: dict) -> list:
        return result["violations"]["personal_token"]

    # ── opt-in ──────────────────────────────────────────────────────────────
    def test_without_a_declaration_the_word_still_fires(self):
        # The baseline the allowance is measured against. The town name is a
        # real boundary hit for the surname and nothing infers otherwise.
        self.assertTrue(self._hits(
            self._scan("offices in " + PLACE_PREFIX + PLACE_SURNAME,
                       [PLACE_SURNAME])))

    def test_with_a_declaration_the_word_is_allowed(self):
        result = self._scan("offices in " + PLACE_PREFIX + PLACE_SURNAME,
                            [PLACE_SURNAME],
                            allowances={PLACE_SURNAME.lower()})
        self.assertEqual(self._hits(result), [])

    def test_a_declaration_is_never_inferred_from_the_word_itself(self):
        # Nothing in the guard consults a dictionary: an ordinary English word
        # that was NOT declared keeps full protection.
        for word in (COLOR_SURNAME, LENGTH_SURNAME, SPEED_SURNAME, ROOM_SURNAME):
            with self.subTest(word=word):
                self.assertTrue(
                    self._hits(self._scan(f"the {word} report", [word])))

    def test_the_env_channel_declares_an_allowance(self):
        os.environ[check_public.WORD_ALLOWANCE_ENV_VAR] = (
            f"# note\n{COLOR_SURNAME}, {LENGTH_SURNAME}\n")
        with mock.patch.object(check_public, "_load_shared_config",
                               return_value=None):
            self.assertEqual(check_public.word_token_allowances(),
                             {COLOR_SURNAME.lower(), LENGTH_SURNAME.lower()})

    def test_the_example_config_declares_nothing(self):
        # A public clone must never inherit an allowance it did not choose.
        stub = _ExampleConfigStub
        with mock.patch.object(check_public, "_load_shared_config",
                               return_value=stub):
            self.assertEqual(check_public.word_token_allowances(), set())

    # ── loud ────────────────────────────────────────────────────────────────
    def test_the_report_names_the_token_and_the_count(self):
        text = (f"{PLACE_SURNAME} it. The {PLACE_SURNAME} is closed. "
                f"{PLACE_PREFIX}{PLACE_SURNAME}.")
        result = self._scan(text, [PLACE_SURNAME],
                            allowances={PLACE_SURNAME.lower()})
        self.assertEqual(result["word_allowances"]["reduced"], {PLACE_SURNAME: 3})
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            check_public.print_report(result)
        printed = buf.getvalue()
        self.assertIn("word allowance", printed)
        self.assertIn(f"'{PLACE_SURNAME}'", printed)
        self.assertIn("REDUCED", printed)
        self.assertIn("3 occurrence(s) SKIPPED", printed)

    def test_the_report_prints_even_on_a_clean_tree(self):
        # Silence on a passing run is how an allowance becomes something nobody
        # remembers granting.
        result = self._scan("nothing to see", [PLACE_SURNAME],
                            allowances={PLACE_SURNAME.lower()})
        self.assertTrue(result["ok"], result["violations"])
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            check_public.print_report(result)
        self.assertIn("word allowance", buf.getvalue())

    def test_a_declaration_that_reaches_nothing_is_reported_as_ineffective(self):
        result = self._scan("nothing", ["jordan.rivers"], allowances={"jordan.rivers"})
        self.assertEqual(result["word_allowances"]["ineffective"], ["jordan.rivers"])
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            check_public.print_report(result)
        self.assertIn("NO effect", buf.getvalue())

    # ── narrow: never reaches a high-specificity token ──────────────────────
    def test_an_allowance_cannot_weaken_an_email_a_handle_or_a_home_basename(self):
        cases = [
            ("jordan.rivers" + "@" + "example.com", "the address is "),
            ("jordanrivers", "linkedin.com/in/"),
            # The sharpest case: a home-directory basename that IS an ordinary
            # word. Declaring it changes nothing, because provenance put it on
            # containment and an allowance only ever reaches a boundary token.
            (COLOR_SURNAME.lower(), "/Users/"),
        ]
        for token, prefix in cases:
            with self.subTest(token=token):
                result = self._scan(prefix + token, [token],
                                    allowances={check_public._normalize_safe_word(token)},
                                    forced={token})
                self.assertTrue(self._hits(result),
                                f"an allowance weakened high-specificity {token!r}")

    def test_an_allowance_cannot_weaken_a_name_compound(self):
        parts = ["Alex", COLOR_SURNAME]
        compounds = check_public._name_compounds(parts)
        tokens = sorted(compounds | {COLOR_SURNAME})
        glued = ("alex" + COLOR_SURNAME.lower())
        # The surname is declared; every compound spelling of the full name is
        # not. Split literals again (see the module docstring): a contiguous
        # '/Users/<name>' or 'linkedin.com/in/<handle>' in this tracked source
        # would trip the guard's own structural-PII scan.
        for text in ("linkedin.com/in/" + glued, "/Users/" + glued + "/x",
                     "a" + COLOR_SURNAME.lower() + "@" + "corp.com",
                     f"acme-alex-{COLOR_SURNAME.lower()}/meta.yaml",
                     f"Contact: Alex {COLOR_SURNAME}"):
            with self.subTest(text=text):
                result = self._scan(text, tokens,
                                    allowances={COLOR_SURNAME.lower()},
                                    forced=compounds)
                self.assertTrue(self._hits(result),
                                f"the full name went unreported in {text!r}")

    def test_the_full_name_is_caught_even_when_both_parts_are_allowed(self):
        # The worst case the allowance has to survive: BOTH name parts are
        # ordinary words. Only the joined/glued compounds stand between the
        # owner's full name and a public repo.
        first, last = LENGTH_SURNAME, COLOR_SURNAME
        parts = [first, last]
        compounds = check_public._name_compounds(parts)
        tokens = sorted(compounds | set(parts))
        both = {first.lower(), last.lower()}
        lo_first, lo_last = first.lower(), last.lower()
        for text in (f"Contact: {first} {last}", f"{last}, {first}",
                     f"{lo_first}-{lo_last}/resume",
                     f"{first}{last}_Resume.docx", f"{lo_first}_{lo_last}"):
            with self.subTest(text=text):
                result = self._scan(text, tokens, allowances=both,
                                    forced=compounds)
                self.assertTrue(self._hits(result),
                                f"the full name went unreported in {text!r}")

    # ── still armed ─────────────────────────────────────────────────────────
    def test_an_allowed_token_still_arms_the_guard(self):
        # An allowance narrows WHERE a token is reported. It must never remove
        # the token, because an empty identity set is the unarmed exit-2 state
        # in which everything reports "Safe to publish".
        os.environ[check_public.TOKENS_ENV_VAR] = COLOR_SURNAME
        os.environ[check_public.WORD_ALLOWANCE_ENV_VAR] = COLOR_SURNAME
        try:
            with mock.patch.object(check_public, "_load_shared_config",
                                   return_value=_ExampleConfigStub):
                self.assertIn(COLOR_SURNAME, check_public.identity_tokens())
                self.assertIn(COLOR_SURNAME.lower(),
                              check_public.word_token_allowances())
        finally:
            os.environ.pop(check_public.TOKENS_ENV_VAR, None)

    def test_no_declaration_means_no_allowance_block_at_all(self):
        result = self._scan("ordinary text", ["Rivers"])
        self.assertIsNone(result["word_allowances"])


class ExporterMatchesTheGuardTests(unittest.TestCase):
    """The exporter's exclusion screen and the guard must agree, always.

    A rule that differed would either drop files the guard passes (a silently
    incomplete export) or ship files the guard fails (an export that cannot be
    published at all).
    """

    def test_a_word_internal_hit_no_longer_excludes_a_file(self):
        # 'Ever' occurs in config.example.yaml only inside 'never'. Under pure
        # containment that excluded the file from every export.
        self.assertIsNone(export_public._deny_reason("config.example.yaml",
                                                     ["Ever"]))

    def test_a_real_leak_still_excludes_a_file(self):
        reason = export_public._deny_reason("config.example.yaml", ["Rivers"])
        self.assertIsNotNone(reason)
        self.assertTrue(reason.startswith("token"))

    def test_a_glued_compound_still_excludes_a_file(self):
        reason = export_public._deny_reason("config.example.yaml",
                                            ["jordanrivers"])
        self.assertIsNotNone(reason)


class PrivateSkillTests(unittest.TestCase):
    def test_private_skill_with_tracked_files_flags(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            files = {
                "skills/secretskill/SKILL.md":
                    "---\nname: secretskill\nvisibility: private\n---\nbody\n",
                "skills/secretskill/notes.md": "private\n",
            }
            tracked = _write_tree(root, files)
            result = check_public.scan(root=root, tracked=tracked, tokens=[])
        self.assertFalse(result["ok"])
        self.assertTrue(result["violations"]["private_skill_tracked"])

    def test_public_skill_is_clean(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            files = {
                "skills/openskill/SKILL.md":
                    "---\nname: openskill\nvisibility: public\n---\nbody\n",
                "skills/openskill/notes.md": "public\n",
            }
            tracked = _write_tree(root, files)
            result = check_public.scan(root=root, tracked=tracked, tokens=[])
        self.assertTrue(result["ok"], result["violations"])


class SkillNotesTests(unittest.TestCase):
    """The per-skill private-notes folder, under BOTH of its names.

    Phase 5 renamed ``references_private/`` to ``skill-notes/``. Keying on the old
    name alone left the rule enforcing nothing at its stated purpose: notes under the
    new name inside the public ``skills/`` tree walked past both guards. Nothing
    leaked only because the notes also moved under ``private/``, which both tools deny
    wholesale — a coincidence, not the rule doing its job.
    """

    def _scan_planted(self, rel: str) -> dict:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            tracked = _write_tree(root, {rel: "candidate-specific notes\n"})
            return check_public.scan(root=root, tracked=tracked, tokens=[])

    def test_both_folder_names_are_flagged_by_guard(self):
        for rel in ("skills/job-search/references_private/notes.md",
                    "skills/job-search/skill-notes/notes.md"):
            with self.subTest(planted=rel):
                result = self._scan_planted(rel)
                self.assertFalse(result["ok"])
                self.assertEqual([v["path"] for v in result["violations"]["skill_notes"]],
                                 [rel])

    def test_both_folder_names_are_pruned_by_exporter(self):
        for rel in ("x/references_private/y.md", "x/skill-notes/y.md"):
            with self.subTest(planted=rel):
                self.assertEqual(export_public._deny_reason(rel, []), "skill-notes")

    def test_a_similarly_named_file_is_not_flagged(self):
        """Matching is per path SEGMENT — this repo tracks a task folder whose name
        ends in ``-skill-notes``, and denying it would make the guard unusable."""
        rel = "tasks/0_backlog/2026-07-30-leak-guard-does-not-know-skill-notes/task.md"
        self.assertEqual(check_public.find_skill_notes_violations([rel]), [])
        self.assertIsNone(export_public._deny_reason(rel, []))

    def test_the_denied_names_still_name_something_real(self):
        """The rename that disarmed this check would have failed HERE first.

        ``verify_links.py --require-roots`` pins its prefix constants against the
        tree; nothing pinned these. This ties the deny list to the accessor that
        decides where the notes actually live, so moving the folder without teaching
        the guard is a test failure rather than a silent disarm.
        """
        sys.path.insert(0, str(REPO_ROOT / "automation" / "shared"))
        import config  # noqa: PLC0415
        live = config.skill_references_dir("resume-writer").parent.name
        self.assertIn(live, check_public.SKILL_NOTES_DIRNAMES,
                      f"config.skill_references_dir() resolves under '{live}/', which "
                      "check_public.SKILL_NOTES_DIRNAMES does not deny")

    def test_env_tokens_ignore_comment_lines(self):
        # The env var may be populated verbatim from private/leak_tokens.txt
        # (e.g. a CI secret), so '#' comment lines must not become tokens.
        os.environ[check_public.TOKENS_ENV_VAR] = (
            "# employer, school, extra handles\nRealToken\n#\n , SecondToken,\n")
        try:
            toks = check_public.personal_tokens()
        finally:
            os.environ.pop(check_public.TOKENS_ENV_VAR, None)
        self.assertIn("RealToken", toks)
        self.assertIn("SecondToken", toks)
        self.assertNotIn("school", toks)
        self.assertNotIn("extra handles", toks)
        self.assertFalse([t for t in toks if t.startswith("#")])


class _ExampleConfigStub:
    """Stands in for automation/shared/config.py resolving to the EXAMPLE config.

    That is the state a fresh clone / a wrong cwd / a missing overlay lands in, and
    the one where ``_identity_tokens`` deliberately returns nothing.
    """

    EXAMPLE_CONFIG = Path("/nonexistent-checkout/config.example.yaml")
    CONFIG_FILENAME = "config.yaml"
    ENV_VAR = "JOBHUNT_CONFIG"

    @staticmethod
    def config_path() -> Path:
        return Path("/nonexistent-checkout/config.example.yaml")

    @staticmethod
    def candidate_name() -> str:
        return "Jordan Rivers"

    @staticmethod
    def contact_line() -> str:
        return "jordan.rivers@example.com"


class ArmingTests(unittest.TestCase):
    """The guard must refuse to run when it cannot see the real identity.

    Gating on the UNION of token sources is the bug: private/leak_tokens.txt keeps
    the union non-empty (employers, school) while the name/email/handles — the
    things a leak actually looks like — are absent.
    """

    def setUp(self):
        self._saved_env = os.environ.pop(check_public.TOKENS_ENV_VAR, None)

    def tearDown(self):
        os.environ.pop(check_public.TOKENS_ENV_VAR, None)
        if self._saved_env is not None:
            os.environ[check_public.TOKENS_ENV_VAR] = self._saved_env

    def test_example_config_yields_zero_identity_tokens(self):
        with mock.patch.object(check_public, "_load_shared_config",
                               return_value=_ExampleConfigStub):
            self.assertEqual(check_public.identity_tokens(), set())

    def test_supplementary_tokens_alone_never_arm_the_guard(self):
        # The exact fail-open shape: a non-empty leak-token file, zero identity.
        with tempfile.TemporaryDirectory() as td:
            leak_file = Path(td) / "leak_tokens.txt"
            leak_file.write_text("# comment\nAcmeRobotics\nStateUniversity\n",
                                 encoding="utf-8")
            with mock.patch.object(check_public, "LEAK_TOKENS_FILES", [leak_file]), \
                 mock.patch.object(check_public, "_overlay_skill_name_tokens",
                                   return_value=set()), \
                 mock.patch.object(check_public, "_load_shared_config",
                                   return_value=_ExampleConfigStub):
                self.assertEqual(check_public.identity_tokens(), set())
                self.assertEqual(check_public.supplementary_tokens(),
                                 {"AcmeRobotics", "StateUniversity"})
                # The union is non-empty — which is why the union cannot be the gate.
                self.assertTrue(check_public.personal_tokens())

    def test_env_var_arms_the_guard(self):
        os.environ[check_public.TOKENS_ENV_VAR] = "RealName,realname@corp.example"
        with mock.patch.object(check_public, "_load_shared_config",
                               return_value=_ExampleConfigStub):
            self.assertIn("RealName", check_public.identity_tokens())

    def test_overlay_skill_names_are_derived_without_a_public_name_list(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            skill = root / "private/skills/hidden-practice"
            skill.mkdir(parents=True)
            (skill / "SKILL.md").write_text(
                "---\nvisibility: private\n---\n", encoding="utf-8")
            notes = root / "private/skills/skill-notes"
            notes.mkdir()

            self.assertEqual(
                check_public._overlay_skill_name_tokens(root),
                {"hidden-practice"},
            )

    def test_unarmed_report_names_the_config_it_looked_for(self):
        with mock.patch.object(check_public, "_load_shared_config",
                               return_value=_ExampleConfigStub):
            text = "\n".join(check_public.unarmed_report())
        self.assertIn("config.yaml", text)
        self.assertIn("JOBHUNT_CONFIG", text)
        self.assertIn("config.example.yaml", text)
        self.assertIn(check_public.TOKENS_ENV_VAR, text)


class _PathStubConfig:
    """A config layer whose active + example paths the test chooses."""

    def __init__(self, active: Path, example: Path):
        self._active = active
        self.EXAMPLE_CONFIG = example
        self.CONFIG_FILENAME = "config.yaml"
        self.ENV_VAR = "JOBHUNT_CONFIG"

    def config_path(self) -> Path:
        return self._active

    @staticmethod
    def candidate_name() -> str:
        return "Rowan Ashdown"

    @staticmethod
    def contact_line() -> str:
        return "rowan.ashdown" + "@" + "acme-robotics" + ".io"


_EXAMPLE_YAML = "candidate:\n  name: Jordan Rivers\n"
_REAL_YAML = "candidate:\n  name: Rowan Ashdown\n"


class ExampleConfigIdentityTests(unittest.TestCase):
    """"Is this the fictional example?" must be about IDENTITY, not location.

    Comparing two ABSOLUTE paths only works while both live in the same tree. The
    exporter runs this guard with ``cwd`` inside a freshly copied export while an
    inherited absolute ``$JOBHUNT_CONFIG`` still points at the SOURCE checkout, so
    the two paths differ, the example persona is taken for the owner's real
    identity, and a clean export fails on every "Jordan Rivers" in its own docs.
    """

    def _two_trees(self, td: str, active_name: str, active_text: str):
        example = Path(td) / "source" / "config.example.yaml"
        example.parent.mkdir(parents=True, exist_ok=True)
        example.write_text(_EXAMPLE_YAML, encoding="utf-8")
        active = Path(td) / "export" / active_name
        active.parent.mkdir(parents=True, exist_ok=True)
        active.write_text(active_text, encoding="utf-8")
        return _PathStubConfig(active=active, example=example)

    def test_a_copy_of_the_example_in_another_tree_is_still_the_example(self):
        with tempfile.TemporaryDirectory() as td:
            stub = self._two_trees(td, "config.example.yaml", _EXAMPLE_YAML)
            self.assertEqual(check_public._identity_tokens(stub), set())

    def test_a_copy_under_a_different_filename_is_still_the_example(self):
        # Content is the test, so the name never decides.
        with tempfile.TemporaryDirectory() as td:
            stub = self._two_trees(td, "config.yaml", _EXAMPLE_YAML)
            self.assertEqual(check_public._identity_tokens(stub), set())

    def test_a_real_config_named_config_example_yaml_is_still_real(self):
        # The safety requirement on the other side: this must NOT become a way for
        # an owner's real config to disarm the guard by being named the example.
        with tempfile.TemporaryDirectory() as td:
            stub = self._two_trees(td, "config.example.yaml", _REAL_YAML)
            toks = check_public._identity_tokens(stub)
        # assertTrue, not assertIn: a failure must not dump a token set that
        # carries the machine's home-directory name.
        self.assertTrue("Rowan" in toks,
                        "a real config must still contribute identity tokens")
        self.assertTrue("Ashdown" in toks)

    def test_the_report_does_not_call_a_copied_example_a_real_config(self):
        with tempfile.TemporaryDirectory() as td:
            stub = self._two_trees(td, "config.example.yaml", _EXAMPLE_YAML)
            with mock.patch.object(check_public, "_load_shared_config",
                                   return_value=stub):
                status = check_public.config_identity_status()
                unarmed = "\n".join(check_public.unarmed_report())
        self.assertIn("fictional example config", status)
        self.assertIn("the TRACKED example fallback", unarmed)

    def test_an_unreadable_config_is_not_silently_declared_the_example(self):
        # Fail toward "real": a config the guard cannot compare must not be waved
        # through as the fictional persona.
        with tempfile.TemporaryDirectory() as td:
            stub = self._two_trees(td, "config.yaml", _REAL_YAML)
            Path(stub.EXAMPLE_CONFIG).unlink()
            toks = check_public._identity_tokens(stub)
        self.assertTrue("Rowan" in toks)


class ArmingCLITests(unittest.TestCase):
    """End-to-end: the CLI exits non-zero when config discovery finds no identity."""

    def _run(self, extra_args: list[str]) -> subprocess.CompletedProcess:
        env = dict(os.environ)
        env.pop(check_public.TOKENS_ENV_VAR, None)
        # Force discovery onto the tracked example config: that is the "found
        # nothing real" state, reached in a fresh clone or a fork CI run.
        env["JOBHUNT_CONFIG"] = str(REPO_ROOT / "config.example.yaml")
        return subprocess.run(
            [sys.executable, str(REPO_ROOT / "automation/publish/check_public.py"),
             *extra_args],
            cwd=REPO_ROOT, capture_output=True, text=True, env=env,
        )

    def test_unarmed_run_exits_nonzero(self):
        proc = self._run([])
        self.assertEqual(proc.returncode, check_public.EXIT_UNARMED, proc.stdout)
        self.assertIn("UNARMED", proc.stdout)
        self.assertNotIn("OK: no public-repo leaks detected", proc.stdout)

    def test_allow_unarmed_still_passes_on_the_clean_tree(self):
        proc = self._run(["--allow-unarmed"])
        self.assertEqual(proc.returncode, check_public.EXIT_OK,
                         proc.stdout + proc.stderr)
        self.assertIn("UNARMED", proc.stderr)
        self.assertIn("Safe to publish", proc.stdout)


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-c", "user.email=t@example.com", "-c", "user.name=T",
         "-c", "commit.gpgsign=false", *args],
        cwd=repo, check=True, capture_output=True, text=True,
    )


class StagedIndexTests(unittest.TestCase):
    """``--staged`` scans the INDEX, so unstaged edits neither hide nor cause a fail."""

    def _repo(self, td: str) -> Path:
        repo = Path(td) / "repo"
        repo.mkdir()
        _git(repo, "init", "-q")
        return repo

    def test_staged_token_is_caught(self):
        with tempfile.TemporaryDirectory() as td:
            repo = self._repo(td)
            (repo / "notes.md").write_text("hello SuperSecretSlug\n", encoding="utf-8")
            _git(repo, "add", "notes.md")
            result = check_public.scan_staged(repo, tokens=["SuperSecretSlug"])
        self.assertFalse(result["ok"])
        self.assertTrue(result["violations"]["personal_token"])

    def test_unstaged_edit_is_not_scanned(self):
        # The worktree carries the token; the INDEX does not. Committing what is
        # staged is safe, so the guard must pass.
        with tempfile.TemporaryDirectory() as td:
            repo = self._repo(td)
            (repo / "notes.md").write_text("clean\n", encoding="utf-8")
            _git(repo, "add", "notes.md")
            (repo / "notes.md").write_text("hello SuperSecretSlug\n", encoding="utf-8")
            result = check_public.scan_staged(repo, tokens=["SuperSecretSlug"])
        self.assertTrue(result["ok"], result["violations"])

    def test_committed_file_edited_only_in_worktree_is_not_scanned(self):
        with tempfile.TemporaryDirectory() as td:
            repo = self._repo(td)
            (repo / "notes.md").write_text("clean\n", encoding="utf-8")
            _git(repo, "add", "notes.md")
            _git(repo, "commit", "-qm", "init")
            (repo / "notes.md").write_text("hello SuperSecretSlug\n", encoding="utf-8")
            (repo / "other.md").write_text("also clean\n", encoding="utf-8")
            _git(repo, "add", "other.md")
            result = check_public.scan_staged(repo, tokens=["SuperSecretSlug"])
        self.assertTrue(result["ok"], result["violations"])
        self.assertEqual(result["tracked_file_count"], 1)

    def test_staged_private_overlay_path_is_caught(self):
        # ``git add -f private/`` (trailing slash) stages with exit 0 and no output.
        with tempfile.TemporaryDirectory() as td:
            repo = self._repo(td)
            (repo / ".gitignore").write_text("private/\n", encoding="utf-8")
            (repo / "private").mkdir()
            (repo / "private" / "profile.md").write_text("real data\n", encoding="utf-8")
            _git(repo, "add", ".gitignore")
            _git(repo, "add", "-f", "private/")
            result = check_public.scan_staged(repo, tokens=[])
        self.assertFalse(result["ok"])
        self.assertEqual([v["path"] for v in result["violations"]["personal_overlay"]],
                         ["private/profile.md"])

    def test_staged_private_product_tree_is_caught_on_path_alone(self):
        with tempfile.TemporaryDirectory() as td:
            repo = self._repo(td)
            (repo / "applications").mkdir()
            (repo / "applications" / "notes.md").write_text("x\n", encoding="utf-8")
            _git(repo, "add", "applications/notes.md")
            result = check_public.scan_staged(repo, tokens=[])
        self.assertFalse(result["ok"])
        self.assertTrue(result["violations"]["path_denylist"])

    def test_staged_deletion_is_not_a_finding(self):
        with tempfile.TemporaryDirectory() as td:
            repo = self._repo(td)
            (repo / "notes.md").write_text("clean\n", encoding="utf-8")
            _git(repo, "add", "notes.md")
            _git(repo, "commit", "-qm", "init")
            _git(repo, "rm", "-q", "notes.md")
            result = check_public.scan_staged(repo, tokens=["SuperSecretSlug"])
        self.assertTrue(result["ok"], result["violations"])
        self.assertEqual(result["tracked_file_count"], 0)

    def test_empty_index_scan_is_clean(self):
        with tempfile.TemporaryDirectory() as td:
            repo = self._repo(td)
            result = check_public.scan_staged(repo, tokens=["SuperSecretSlug"])
        self.assertTrue(result["ok"], result["violations"])

    def test_staged_symlink_target_is_scanned_as_text(self):
        # An overlay symlink's blob IS its target path; that path names private data.
        with tempfile.TemporaryDirectory() as td:
            repo = self._repo(td)
            os.symlink("../private/skills/hidden-practice", repo / "link")
            _git(repo, "add", "link")
            result = check_public.scan_staged(repo, tokens=["hidden-practice"])
        self.assertFalse(result["ok"])
        self.assertTrue(result["violations"]["personal_token"])

    def test_staged_broken_symlink_has_no_unreadable_file(self):
        """The check-8 failure mode does NOT exist in ``--staged``, by construction.

        ``_materialize_index`` writes the INDEX blob of every staged path into a
        scratch tree and rewrites each symlink as the text of its target, so
        nothing the pre-commit hook scans can be a dangling link. The target text
        is still scanned (previous test); this pins that the hook does not start
        rejecting a commit that merely adds a link into a not-yet-created dir.
        """
        with tempfile.TemporaryDirectory() as td:
            repo = self._repo(td)
            os.symlink("nowhere/missing.md", repo / "link")
            _git(repo, "add", "link")
            result = check_public.scan_staged(repo, tokens=[])
        self.assertTrue(result["ok"], result["violations"])
        self.assertEqual(result["unreadable_files"], [])
        self.assertEqual(result["files_read"], 1)


class GitObjectTests(unittest.TestCase):
    """``--git-object`` scans a committed tree, never mutable checkout state."""

    def _repo(self, td: str) -> Path:
        repo = Path(td) / "repo"
        repo.mkdir()
        _git(repo, "init", "-q")
        return repo

    def _commit(self, repo: Path, text: str) -> str:
        (repo / "notes.md").write_text(text, encoding="utf-8")
        _git(repo, "add", "notes.md")
        _git(repo, "commit", "-qm", "snapshot")
        return _git(repo, "rev-parse", "HEAD").stdout.strip()

    def test_dirty_clean_edit_cannot_hide_token_in_object(self):
        with tempfile.TemporaryDirectory() as td:
            repo = self._repo(td)
            oid = self._commit(repo, "hello SuperSecretSlug\n")
            (repo / "notes.md").write_text("clean now\n", encoding="utf-8")

            result = check_public.scan_git_object(
                repo, oid, tokens=["SuperSecretSlug"])

        self.assertFalse(result["ok"])
        self.assertTrue(result["violations"]["personal_token"])
        self.assertEqual(result["mode"], "git-object")

    def test_dirty_token_edit_does_not_taint_clean_object(self):
        with tempfile.TemporaryDirectory() as td:
            repo = self._repo(td)
            oid = self._commit(repo, "clean\n")
            (repo / "notes.md").write_text(
                "hello SuperSecretSlug\n", encoding="utf-8")

            result = check_public.scan_git_object(
                repo, oid, tokens=["SuperSecretSlug"])

        self.assertTrue(result["ok"], result["violations"])

    def test_non_head_object_is_scanned(self):
        with tempfile.TemporaryDirectory() as td:
            repo = self._repo(td)
            leaky_oid = self._commit(repo, "hello SuperSecretSlug\n")
            clean_oid = self._commit(repo, "clean\n")
            self.assertEqual(_git(repo, "rev-parse", "HEAD").stdout.strip(), clean_oid)

            result = check_public.scan_git_object(
                repo, leaky_oid, tokens=["SuperSecretSlug"])

        self.assertFalse(result["ok"])
        self.assertEqual(result["git_object"], leaky_oid)

    def test_object_from_linked_worktree_is_scanned_without_touching_primary(self):
        with tempfile.TemporaryDirectory() as td:
            repo = self._repo(td)
            primary_oid = self._commit(repo, "clean\n")
            linked = Path(td) / "linked"
            _git(repo, "worktree", "add", "-q", "-b", "linked-topic", str(linked))
            (linked / "notes.md").write_text(
                "hello SuperSecretSlug\n", encoding="utf-8")
            _git(linked, "add", "notes.md")
            _git(linked, "commit", "-qm", "linked leak")
            linked_oid = _git(linked, "rev-parse", "HEAD").stdout.strip()
            primary_status = _git(repo, "status", "--porcelain=v1").stdout

            result = check_public.scan_git_object(
                repo, linked_oid, tokens=["SuperSecretSlug"])

            self.assertFalse(result["ok"])
            self.assertEqual(_git(repo, "rev-parse", "HEAD").stdout.strip(), primary_oid)
            self.assertEqual(
                _git(repo, "status", "--porcelain=v1").stdout, primary_status)

    def test_scan_does_not_change_head_index_or_worktree(self):
        with tempfile.TemporaryDirectory() as td:
            repo = self._repo(td)
            oid = self._commit(repo, "committed\n")
            (repo / "notes.md").write_text("dirty\n", encoding="utf-8")
            before_head = _git(repo, "rev-parse", "HEAD").stdout
            before_index = _git(repo, "write-tree").stdout
            before_status = _git(repo, "status", "--porcelain=v1").stdout

            check_public.scan_git_object(repo, oid, tokens=[])

            self.assertEqual(_git(repo, "rev-parse", "HEAD").stdout, before_head)
            self.assertEqual(_git(repo, "write-tree").stdout, before_index)
            self.assertEqual(
                _git(repo, "status", "--porcelain=v1").stdout, before_status)

    def test_object_symlink_target_is_scanned_as_text(self):
        with tempfile.TemporaryDirectory() as td:
            repo = self._repo(td)
            os.symlink("../private/skills/hidden-practice", repo / "link")
            _git(repo, "add", "link")
            _git(repo, "commit", "-qm", "symlink")
            oid = _git(repo, "rev-parse", "HEAD").stdout.strip()

            result = check_public.scan_git_object(
                repo, oid, tokens=["hidden-practice"])

        self.assertFalse(result["ok"])
        self.assertTrue(result["violations"]["personal_token"])


class UnreadableFileTests(unittest.TestCase):
    """Check 8: a tracked path the guard could not OPEN is a finding, not a skip.

    The dividing line is OPENABILITY, not extractability:

    * never opened (dangling symlink, permission error, I/O error) -> FAIL. The
      bytes ship and the guard saw none of them.
    * opened but holding no scannable text (binary blob, non-UTF-8 file, image,
      corrupt container) -> counted and named in the summary, never fatal. The
      tree tracks such files on purpose (``examples/screenshots/*.jpg``,
      ``examples/fixtures/resume-writer/empty-corrupt/corrupt-docx.docx``), and a
      guard that red-lights them is a guard someone turns off.
    """

    def _scan(self, files: dict, extra=None) -> dict:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            tracked = _write_tree(root, files)
            if extra is not None:
                tracked = sorted(set(tracked) | set(extra(root)))
            return check_public.scan(root=root, tracked=tracked, tokens=[])

    def _reasons(self, result: dict, key: str) -> dict:
        out: dict[str, int] = {}
        for item in result[key]:
            out[item["reason"]] = out.get(item["reason"], 0) + 1
        return out

    # ── never opened: FAIL ───────────────────────────────────────────────────
    def test_broken_symlink_is_a_finding(self):
        def plant(root: Path) -> list[str]:
            os.symlink("../nowhere/missing.md", root / "docs" / "dangling.md")
            return ["docs/dangling.md"]

        result = self._scan({"docs/real.md": "clean\n"}, extra=plant)
        self.assertFalse(result["ok"])
        self.assertEqual([i["path"] for i in result["unreadable_files"]],
                         ["docs/dangling.md"])
        self.assertEqual(result["unreadable_files"][0]["reason"],
                         check_public.UNREADABLE_BROKEN_SYMLINK)
        self.assertEqual([i["path"] for i in result["violations"]["unreadable_file"]],
                         ["docs/dangling.md"])

    def test_broken_symlink_is_named_in_the_report(self):
        def plant(root: Path) -> list[str]:
            os.symlink("../nowhere/missing.md", root / "docs" / "dangling.md")
            return ["docs/dangling.md"]

        result = self._scan({"docs/real.md": "clean\n"}, extra=plant)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            check_public.print_report(result)
        out = buf.getvalue()
        self.assertIn("[8] Unreadable tracked files", out)
        self.assertIn("BROKEN-SYMLINK", out)
        self.assertIn("docs/dangling.md", out)
        self.assertNotIn("OK: no public-repo leaks detected", out)

    def test_broken_symlink_exits_nonzero_end_to_end(self):
        """The planted defect from the task, through the real CLI."""
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "repo"
            (repo / "docs").mkdir(parents=True)
            _git(repo, "init", "-q")
            (repo / "docs" / "real.md").write_text("clean\n", encoding="utf-8")
            os.symlink("../nowhere/missing.md", repo / "docs" / "dangling.md")
            _git(repo, "add", "-A")
            result = check_public.scan(root=repo, tokens=[])
        self.assertFalse(result["ok"])
        self.assertEqual(
            check_public.EXIT_VIOLATIONS if not result["ok"] else check_public.EXIT_OK,
            check_public.EXIT_VIOLATIONS)
        self.assertIn("docs/dangling.md",
                      [i["path"] for i in result["unreadable_files"]])

    @unittest.skipIf(hasattr(os, "geteuid") and os.geteuid() == 0,
                     "root can read a 0o000 file, so the condition cannot be planted")
    def test_permission_denied_is_a_finding(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            tracked = _write_tree(root, {"docs/secret.md": "clean\n"})
            (root / "docs" / "secret.md").chmod(0o000)
            try:
                result = check_public.scan(root=root, tracked=tracked, tokens=[])
            finally:
                (root / "docs" / "secret.md").chmod(0o644)
        self.assertFalse(result["ok"])
        self.assertEqual(result["unreadable_files"][0]["reason"],
                         check_public.UNREADABLE_OPEN_FAILED)
        self.assertIn("PermissionError", result["unreadable_files"][0]["detail"])

    @unittest.skipIf(hasattr(os, "geteuid") and os.geteuid() == 0,
                     "root can read a 0o000 file, so the condition cannot be planted")
    def test_unopenable_binary_is_unreadable_not_unscanned(self):
        # A .docx nobody can open is check 8 (never opened), NOT check 7
        # (opened, no text) — and the examples/ exemption does not cover it,
        # because that allowlist is a claim about extractability.
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            tracked = _write_tree(root, {"examples/doc.docx": b"PK\x03\x04 junk"})
            (root / "examples" / "doc.docx").chmod(0o000)
            try:
                result = check_public.scan(root=root, tracked=tracked, tokens=[])
            finally:
                (root / "examples" / "doc.docx").chmod(0o644)
        self.assertFalse(result["ok"])
        self.assertEqual(result["unscanned_binaries"], [])
        self.assertEqual([i["path"] for i in result["unreadable_files"]],
                         ["examples/doc.docx"])

    # ── opened, nothing to scan: counted, not fatal ──────────────────────────
    def test_undecodable_file_is_read_not_skipped(self):
        # latin-1 text: opened fine, and NOT a binary blob. It used to land in the
        # skip bucket, which meant a real name inside it was never searched for.
        # The coverage that proves the scan now sees it lives in
        # NonUtf8TextScanTests; this pins which bucket it belongs to.
        result = self._scan({"docs/notes.md": b"caf\xe9 r\xe9sum\xe9\n"})
        self.assertTrue(result["ok"], result["violations"])
        self.assertEqual(self._reasons(result, "files_skipped"), {})
        self.assertEqual(result["files_read"], 1)

    def test_binary_blob_without_a_known_extension_skips_quietly(self):
        # A NUL-bearing blob (the tracked ``*.json.zst`` job payloads look like
        # this): no text exists to substring-scan.
        result = self._scan({"examples/store/blob.zst": b"\x28\xb5\x2f\xfd\x00\x00raw"})
        self.assertTrue(result["ok"], result["violations"])
        self.assertEqual(self._reasons(result, "files_skipped"),
                         {check_public.SKIP_BINARY_SNIFF: 1})

    def test_corrupt_docx_outside_examples_still_fails_as_check_7(self):
        result = self._scan({"docs/report.docx": b"this is not a zip archive"})
        self.assertFalse(result["ok"])
        self.assertEqual(result["unscanned_binaries"], ["docs/report.docx"])
        self.assertEqual(result["violations"]["unscanned_binary"][0]["reason"],
                         check_public.SKIP_EXTRACT_FAILED)
        self.assertEqual(result["unreadable_files"], [])

    def test_corrupt_docx_under_examples_is_exempt_but_counted(self):
        # Mirrors the tracked fixture
        # examples/fixtures/resume-writer/empty-corrupt/corrupt-docx.docx.
        result = self._scan(
            {"examples/fixtures/corrupt-docx.docx": b"this is not a zip archive"})
        self.assertTrue(result["ok"], result["violations"])
        self.assertEqual(self._reasons(result, "files_skipped"),
                         {check_public.SKIP_EXTRACT_FAILED: 1})

    # ── symlinks that resolve ────────────────────────────────────────────────
    def test_symlink_to_a_directory_is_read_not_unreadable(self):
        # The 33 tracked ``.claude/skills/<skill> -> ../../skills/<skill>`` links
        # are symlinks to DIRECTORIES: unreadable as files, but their content —
        # the target path — is exactly what git ships, and it is scanned.
        def plant(root: Path) -> list[str]:
            os.symlink("../skills/job-search", root / "host" / "job-search")
            return ["host/job-search"]

        result = self._scan({"skills/job-search/SKILL.md": "---\nname: x\n---\n",
                             "host/.keep": ""}, extra=plant)
        self.assertTrue(result["ok"], result["violations"])
        self.assertEqual(result["unreadable_files"], [])
        self.assertEqual(result["files_skipped"], [])

    def test_symlink_target_text_is_scanned_in_whole_tree_mode_too(self):
        # Parity with --staged (``test_staged_symlink_target_is_scanned_as_text``):
        # a link into the overlay leaks the private path it names.
        def plant(root: Path) -> list[str]:
            os.symlink("../private/skills/hidden-practice", root / "host" / "link")
            return ["host/link"]

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            tracked = _write_tree(root, {"host/.keep": ""})
            tracked = sorted(set(tracked) | set(plant(root)))
            result = check_public.scan(root=root, tracked=tracked,
                                       tokens=["hidden-practice"])
        self.assertFalse(result["ok"])
        hits = result["violations"]["personal_token"]
        self.assertIn("symlink-target", [h["where"] for h in hits])

    # ── accounting ───────────────────────────────────────────────────────────
    def test_every_tracked_path_lands_in_exactly_one_bucket(self):
        def plant(root: Path) -> list[str]:
            os.symlink("../nowhere/missing.md", root / "docs" / "dangling.md")
            os.symlink("real.md", root / "docs" / "alias.md")
            return ["docs/dangling.md", "docs/alias.md"]

        result = self._scan({
            "docs/real.md": "clean\n",
            "docs/notes.md": b"caf\xe9\n",
            "examples/store/blob.zst": b"\x00raw",
            "examples/screenshot.png": b"\x89PNG\r\n not-real",
        }, extra=plant)
        self.assertEqual(
            result["files_read"] + len(result["files_skipped"])
            + len(result["unreadable_files"]),
            result["tracked_file_count"])

    def test_summary_reports_how_much_was_actually_read(self):
        result = self._scan({"examples/screenshot.png": b"\x89PNG\r\n not-real",
                             "docs/real.md": "ok\n"})
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            check_public.print_report(result)
        out = buf.getvalue()
        self.assertIn("content read:   1 of 2 file(s)", out)
        self.assertIn("not inspected:  1", out)
        self.assertIn(check_public.SKIP_NO_EXTRACTOR, out)


class NonUtf8TextScanTests(unittest.TestCase):
    """A tracked text file that is not valid UTF-8 must still be SCANNED.

    Counting it as "opened, no text to scan" made the guard certify bytes it had
    never searched: a NUL-free latin-1 ``.md`` carrying the owner's name passed.
    The fix decodes every undecodable byte as latin-1 and leaves valid UTF-8
    sequences alone, so no byte is dropped and no token is split by a replacement
    character. Both halves of that are asserted below, because each single-codec
    fallback misses the case the other one catches.
    """

    def _scan(self, files: dict, tokens=()) -> dict:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            tracked = _write_tree(root, files)
            return check_public.scan(root=root, tracked=tracked, tokens=list(tokens))

    def _reasons(self, result: dict) -> dict:
        out: dict[str, int] = {}
        for item in result["files_skipped"]:
            out[item["reason"]] = out.get(item["reason"], 0) + 1
        return out

    def test_ascii_token_in_a_latin1_file_is_caught(self):
        # The realistic leak: a note pasted in from a non-UTF-8 source. The name
        # is plain ASCII; one accented byte elsewhere is all it took to hide it.
        blob = "Reviewed by Ravenscroft over café\n".encode("latin-1")
        result = self._scan({"docs/notes.md": blob}, tokens=["Ravenscroft"])
        self.assertFalse(result["ok"])
        hits = result["violations"]["personal_token"]
        self.assertEqual([h["where"] for h in hits], ["content"])
        self.assertEqual(hits[0]["path"], "docs/notes.md")
        self.assertEqual(hits[0]["token"], "Ravenscroft")

    def test_latin1_encoded_non_ascii_token_is_caught(self):
        # utf-8 + errors="replace" turns the 0xF8 byte into U+FFFD and SPLITS this
        # token, which is exactly the objection the backlog task raised. Decoding
        # the rejected byte as latin-1 keeps the character, so the match holds.
        blob = "contact Bjørnholm today\n".encode("latin-1")
        result = self._scan({"docs/notes.md": blob}, tokens=["Bjørnholm"])
        self.assertFalse(result["ok"])
        self.assertEqual(result["violations"]["personal_token"][0]["token"],
                         "Bjørnholm")

    def test_utf8_token_survives_a_stray_latin1_byte(self):
        # The mirror case: decoding the WHOLE file as latin-1 would mojibake this
        # UTF-8 token into "ZÃ¼rich" and miss it. Only the bytes UTF-8 rejects are
        # decoded as latin-1; everything it accepts keeps its real characters.
        blob = "office in Zürich\n".encode("utf-8") + b"stray \xe9 byte\n"
        result = self._scan({"docs/notes.md": blob}, tokens=["Zürich"])
        self.assertFalse(result["ok"])
        self.assertEqual(result["violations"]["personal_token"][0]["token"],
                         "Zürich")

    def test_structural_pii_in_a_latin1_file_is_caught_with_zero_tokens(self):
        blob = f"café owner {REAL_EMAIL}\n".encode("latin-1")
        result = self._scan({"docs/notes.md": blob}, tokens=[])
        self.assertFalse(result["ok"])
        self.assertIn("email",
                      {v["kind"] for v in result["violations"]["structural_pii"]})

    def test_a_non_utf8_file_counts_as_read_not_skipped(self):
        result = self._scan({"docs/notes.md": b"caf\xe9 r\xe9sum\xe9\n"}, tokens=[])
        self.assertTrue(result["ok"], result["violations"])
        self.assertEqual(result["files_read"], 1)
        self.assertEqual(self._reasons(result), {})
        self.assertEqual([i["path"] for i in result["fallback_decoded"]],
                         ["docs/notes.md"])

    def test_line_numbers_stay_true_to_the_file(self):
        blob = b"first\n" + "café\n".encode("latin-1") + b"Ravenscroft here\n"
        result = self._scan({"docs/notes.md": blob}, tokens=["Ravenscroft"])
        self.assertEqual(result["violations"]["personal_token"][0]["line"], 3)

    def test_report_names_the_fallback_decode_instead_of_a_skip(self):
        result = self._scan({"docs/notes.md": b"caf\xe9\n", "docs/real.md": "ok\n"},
                            tokens=[])
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            check_public.print_report(result)
        out = buf.getvalue()
        self.assertIn("content read:   2 of 2 file(s)", out)
        self.assertNotIn("not inspected:", out)
        self.assertIn("mixed encoding:", out)
        self.assertIn("docs/notes.md", out)

    def test_binary_blobs_are_still_skipped_not_decoded(self):
        # The NUL sniff runs FIRST and must keep doing so: decoding a compressed
        # payload as latin-1 would produce megabytes of noise to substring-scan.
        result = self._scan({"examples/store/blob.zst": b"\x28\xb5\x2f\xfd\x00\x00raw"},
                            tokens=[])
        self.assertTrue(result["ok"], result["violations"])
        self.assertEqual(self._reasons(result), {check_public.SKIP_BINARY_SNIFF: 1})
        self.assertEqual(result["fallback_decoded"], [])


class TokenSourceUnreadableTests(unittest.TestCase):
    """The guard's own ARMING INPUT must fail closed, like the files it scans.

    ``private/leak_tokens.txt`` supplies the employer/school/product tokens. A
    permission error or an I/O error used to return an empty set, silently
    NARROWING the scan while the guard still printed "Safe to publish". A file
    that is simply ABSENT stays legitimate — the overlay may not be mounted.
    """

    def _clean_tree_scan(self, leak_files: list) -> dict:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            tracked = _write_tree(root, {"docs/real.md": "clean\n"})
            with mock.patch.object(check_public, "LEAK_TOKENS_FILES", leak_files), \
                 mock.patch.object(check_public, "_overlay_skill_name_tokens",
                                   return_value=set()), \
                 mock.patch.object(check_public, "identity_tokens",
                                   return_value={"Ravenscroft"}):
                return check_public.scan(root=root, tracked=tracked)

    def test_absent_token_file_is_legitimate(self):
        with tempfile.TemporaryDirectory() as td:
            missing = Path(td) / "leak_tokens.txt"
            self.assertEqual(check_public.token_source_errors([missing]), [])
            result = self._clean_tree_scan([missing])
        self.assertTrue(result["ok"], result["violations"])

    @unittest.skipIf(hasattr(os, "geteuid") and os.geteuid() == 0,
                     "root can read a 0o000 file, so the condition cannot be planted")
    def test_unreadable_token_file_refuses_to_certify(self):
        with tempfile.TemporaryDirectory() as td:
            leak_file = Path(td) / "leak_tokens.txt"
            leak_file.write_text("AcmeRobotics\n", encoding="utf-8")
            leak_file.chmod(0o000)
            try:
                errors = check_public.token_source_errors([leak_file])
                result = self._clean_tree_scan([leak_file])
            finally:
                leak_file.chmod(0o644)
        self.assertEqual(len(errors), 1)
        self.assertIn("PermissionError", errors[0]["detail"])
        self.assertFalse(result["ok"])
        self.assertEqual(len(result["violations"]["token_source_unreadable"]), 1)

    def test_dangling_token_file_symlink_is_a_finding_not_an_absence(self):
        with tempfile.TemporaryDirectory() as td:
            leak_file = Path(td) / "leak_tokens.txt"
            os.symlink(Path(td) / "nowhere.txt", leak_file)
            errors = check_public.token_source_errors([leak_file])
            result = self._clean_tree_scan([leak_file])
        self.assertEqual(len(errors), 1)
        self.assertFalse(result["ok"])

    @unittest.skipIf(hasattr(os, "geteuid") and os.geteuid() == 0,
                     "root can read a 0o000 file, so the condition cannot be planted")
    def test_unreadable_token_file_is_named_in_the_report(self):
        with tempfile.TemporaryDirectory() as td:
            leak_file = Path(td) / "leak_tokens.txt"
            leak_file.write_text("AcmeRobotics\n", encoding="utf-8")
            leak_file.chmod(0o000)
            try:
                result = self._clean_tree_scan([leak_file])
            finally:
                leak_file.chmod(0o644)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            check_public.print_report(result)
        out = buf.getvalue()
        self.assertNotIn("OK: no public-repo leaks detected", out)
        self.assertIn("[9] Unreadable personal-token source", out)
        self.assertIn("leak_tokens.txt", out)

    def test_non_utf8_token_file_keeps_every_token(self):
        # One stray byte used to drop the WHOLE token set. It must not.
        with tempfile.TemporaryDirectory() as td:
            leak_file = Path(td) / "leak_tokens.txt"
            leak_file.write_bytes("AcmeRobotics\nCaféCorp\n".encode("latin-1"))
            with mock.patch.object(check_public, "LEAK_TOKENS_FILES", [leak_file]), \
                 mock.patch.object(check_public, "_overlay_skill_name_tokens",
                                   return_value=set()):
                self.assertEqual(check_public.supplementary_tokens(),
                                 {"AcmeRobotics", "CaféCorp"})
                self.assertEqual(check_public.token_source_errors([leak_file]), [])

    def test_caller_supplied_tokens_never_touch_the_token_files(self):
        # Fixture scans pass ``tokens=[...]`` and must stay deterministic: the
        # guard did not resolve its own tokens, so there is nothing to report.
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            tracked = _write_tree(root, {"docs/real.md": "clean\n"})
            missing = Path(td) / "nope" / "leak_tokens.txt"
            with mock.patch.object(check_public, "LEAK_TOKENS_FILES", [missing]):
                result = check_public.scan(root=root, tracked=tracked, tokens=[])
        self.assertTrue(result["ok"], result["violations"])
        self.assertEqual(result["violations"]["token_source_unreadable"], [])


class SafeWordTests(unittest.TestCase):
    """Safe words exempt an overlay SKILL NAME that is also an ordinary phrase.

    ``_overlay_skill_name_tokens`` derives a token from every private skill
    folder, so naming a skill after a common phrase retroactively turns
    pre-existing public prose into a leak report. These pin both halves: that the
    exemption works, and — the half that matters — that it can only ever reach the
    auto-derived skill names, never a token the maintainer declared.
    """

    def _tree(self, td, *skill_names):
        root = Path(td)
        for name in skill_names:
            skill = root / "private/skills" / name
            skill.mkdir(parents=True)
            (skill / "SKILL.md").write_text(
                "---\nvisibility: private\n---\n", encoding="utf-8")
        return root

    def _safe_file(self, td, text):
        path = Path(td) / "leak_safe_words.txt"
        path.write_text(text, encoding="utf-8")
        return path

    def test_a_safe_word_drops_that_skill_name_from_the_token_set(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._tree(td, "field-notes", "hidden-practice")
            safe = self._safe_file(td, "# a note\nfield notes\n")
            with mock.patch.object(check_public, "SAFE_WORDS_FILES", [safe]), \
                 mock.patch.object(check_public, "LEAK_TOKENS_FILES", []), \
                 mock.patch.object(check_public, "_overlay_skill_name_tokens",
                                   return_value=check_public._overlay_skill_name_tokens(root)), \
                 mock.patch.object(check_public, "_load_shared_config",
                                   return_value=_ExampleConfigStub):
                # The exempted name is gone; the other private skill is untouched.
                self.assertEqual(check_public.supplementary_tokens(),
                                 {"hidden-practice"})

    def test_separators_are_unified_in_both_directions(self):
        # The folder is hyphenated, the safe word is spaced. Neither spelling is
        # privileged: an underscored folder is covered by the same line.
        for folder in ("field-notes", "field_notes", "field notes"):
            for written in ("field notes", "field-notes", "field_notes"):
                with self.subTest(folder=folder, written=written):
                    with tempfile.TemporaryDirectory() as td:
                        safe = self._safe_file(td, written + "\n")
                        with mock.patch.object(check_public, "SAFE_WORDS_FILES", [safe]):
                            self.assertEqual(
                                check_public._apply_safe_words({folder}), set())

    def test_a_safe_word_matches_the_whole_name_not_a_substring(self):
        # Substring semantics would let a one-letter line exempt every skill —
        # and would let either HALF of a compound name exempt the whole thing.
        with tempfile.TemporaryDirectory() as td:
            safe = self._safe_file(td, "field\nnotes\na\n")
            with mock.patch.object(check_public, "SAFE_WORDS_FILES", [safe]):
                self.assertEqual(
                    check_public._apply_safe_words({"field-notes"}),
                    {"field-notes"},
                )

    def test_a_safe_word_cannot_remove_a_declared_identity_token(self):
        # THE safety property. A mechanism that can un-declare a declared secret
        # is a disarming vector; this one is scoped to derived names only.
        os.environ[check_public.TOKENS_ENV_VAR] = "field-notes,RealName"
        with tempfile.TemporaryDirectory() as td:
            safe = self._safe_file(td, "field notes\nreal name\n")
            with mock.patch.object(check_public, "SAFE_WORDS_FILES", [safe]), \
                 mock.patch.object(check_public, "LEAK_TOKENS_FILES", []), \
                 mock.patch.object(check_public, "_overlay_skill_name_tokens",
                                   return_value={"field-notes"}), \
                 mock.patch.object(check_public, "_load_shared_config",
                                   return_value=_ExampleConfigStub):
                self.assertIn("field-notes", check_public.identity_tokens())
                # Dropped from the derived half...
                self.assertNotIn("field-notes", check_public.supplementary_tokens())
                # ...and still live in the set the scan actually uses.
                self.assertIn("field-notes", check_public.personal_tokens())
                self.assertIn("RealName", check_public.personal_tokens())

    def test_a_safe_word_cannot_remove_a_leak_token_file_line(self):
        with tempfile.TemporaryDirectory() as td:
            leak_file = Path(td) / "leak_tokens.txt"
            leak_file.write_text("AcmeRobotics\n", encoding="utf-8")
            safe = self._safe_file(td, "acme robotics\n")
            with mock.patch.object(check_public, "SAFE_WORDS_FILES", [safe]), \
                 mock.patch.object(check_public, "LEAK_TOKENS_FILES", [leak_file]), \
                 mock.patch.object(check_public, "_overlay_skill_name_tokens",
                                   return_value=set()), \
                 mock.patch.object(check_public, "_load_shared_config",
                                   return_value=_ExampleConfigStub):
                self.assertIn("AcmeRobotics", check_public.supplementary_tokens())

    def test_an_absent_safe_word_file_changes_nothing(self):
        # A public clone has no overlay and no such file; that is not an error.
        with tempfile.TemporaryDirectory() as td:
            missing = Path(td) / "nope" / "leak_safe_words.txt"
            with mock.patch.object(check_public, "SAFE_WORDS_FILES", [missing]):
                self.assertEqual(check_public.safe_words(), set())
                self.assertEqual(check_public._apply_safe_words({"field-notes"}),
                                 {"field-notes"})

    def test_an_unreadable_safe_word_file_widens_the_scan_and_is_reported(self):
        # Opposite fail-direction to a leak-token file, and that is why it is not
        # a violation: losing an exemption over-reports, it never certifies.
        with tempfile.TemporaryDirectory() as td:
            root = self._tree(td, "field-notes")
            safe = Path(td) / "leak_safe_words.txt"
            safe.symlink_to(Path(td) / "does-not-exist.txt")
            with mock.patch.object(check_public, "SAFE_WORDS_FILES", [safe]), \
                 mock.patch.object(check_public, "LEAK_TOKENS_FILES", []), \
                 mock.patch.object(check_public, "_load_shared_config",
                                   return_value=_ExampleConfigStub):
                self.assertEqual(check_public.safe_words(), set())
                # Not exempted — the token stays live.
                self.assertEqual(check_public._apply_safe_words({"field-notes"}),
                                 {"field-notes"})
                report = check_public.safe_word_report(root)
        self.assertTrue(report["unreadable"])
        self.assertEqual(report["exempted"], [])

    def test_the_report_names_a_safe_word_that_has_no_effect(self):
        # Silence here would let the maintainer believe a word is exempt while
        # the union puts it straight back.
        os.environ[check_public.TOKENS_ENV_VAR] = "field-notes"
        with tempfile.TemporaryDirectory() as td:
            root = self._tree(td, "field-notes")
            safe = self._safe_file(td, "field notes\n")
            with mock.patch.object(check_public, "SAFE_WORDS_FILES", [safe]), \
                 mock.patch.object(check_public, "LEAK_TOKENS_FILES", []), \
                 mock.patch.object(check_public, "_load_shared_config",
                                   return_value=_ExampleConfigStub):
                report = check_public.safe_word_report(root)
        self.assertEqual(report["ineffective"], ["field notes"])

    def test_an_unexempted_skill_name_is_still_caught_in_content(self):
        # The guard must keep doing its job for every name NOT declared safe.
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "docs").mkdir(parents=True)
            (root / "docs/leaky.md").write_text(
                "see the hidden-practice skill\n", encoding="utf-8")
            result = check_public.scan(
                root=root, tracked=["docs/leaky.md"], tokens=["hidden-practice"])
        self.assertFalse(result["ok"])
        self.assertTrue(result["violations"]["personal_token"])


class RealTreeStructuralTests(unittest.TestCase):
    """Scan the REAL tracked tree, not a synthetic fixture built from the same literals.

    The synthetic fixtures in the classes above pass whether or not the detector
    still matches the tree that actually ships, so a rename of a private root can
    leave them green with the detector dead. These assert against ``git ls-files``.
    """

    @classmethod
    def setUpClass(cls):
        if not (REPO_ROOT / ".git").exists():
            raise unittest.SkipTest("not a git checkout")
        cls.tracked = check_public.git_tracked_files()

    def test_tracked_tree_has_no_structural_violations(self):
        self.assertEqual(check_public.find_personal_overlay_violations(self.tracked), [])
        self.assertEqual(check_public.find_skill_notes_violations(self.tracked), [])
        self.assertEqual(check_public.find_path_denylist_violations(self.tracked), [])
        self.assertEqual(
            check_public.find_private_skill_violations(REPO_ROOT, self.tracked), [])

    def test_every_root_anchored_gitignore_product_rule_is_denied(self):
        """A private root that is git-ignored must ALSO be path-denied.

        ``.gitignore`` is the other place a private root at the public root is
        named. If a rename adds ``/store/`` there but not to ``_DENY_TREES``, the
        only thing standing between that tree and a publish is a glob that
        ``git add -f`` overrides — this test fails instead.
        """
        # Root-anchored ignore rules that are scratch/build output rather than a
        # private PRODUCT tree. Add here (with a reason) only after checking the
        # tree is genuinely not personal data.
        NON_PRODUCT_ROOTS: set[str] = set()
        text = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
        rules = [ln.strip() for ln in text.splitlines()
                 if ln.strip().startswith("/") and ln.strip().endswith("/")]
        self.assertTrue(rules, "expected root-anchored private-product rules in .gitignore")
        for rule in rules:
            rel = rule.lstrip("/")
            if rel in NON_PRODUCT_ROOTS:
                continue
            probe = rel + "probe.md"
            denied = bool(check_public.find_path_denylist_violations([probe])
                          or check_public.find_personal_overlay_violations([probe]))
            self.assertTrue(denied, f".gitignore rule '{rule}' is not covered by "
                                    "_DENY_TREES / PERSONAL_OVERLAY_PREFIXES")

    def test_deny_trees_are_append_only(self):
        """Historical private-root names are never retired, only added to.

        A rename (``data/``->``store/``, ``interviews/``->``me/``+``companies/``,
        ``job-search-profiles/``->``market/searches/``) must ADD the new name and
        KEEP the old one: a stale checkout or an old branch can still put the
        historical tree at the public root.
        """
        required = {
            "applications/", "interviews/", ".agents/inputs/",
            "data/", "job-search-profiles/",
            "store/", "me/", "companies/", "market/",
        }
        labels = {label for _, label in check_public._DENY_TREES}
        self.assertEqual(required - labels, set(),
                         "a private root name was REMOVED from _DENY_TREES")
        for label in sorted(required):
            probe = label + "probe.md"
            self.assertTrue(check_public.find_path_denylist_violations([probe]),
                            f"{label} is listed but does not match {probe}")

    def test_public_roots_are_not_denied(self):
        """The denylist must not shadow a legitimate public root."""
        for rel in sorted({p.split("/")[0] for p in self.tracked if "/" in p}):
            probe = f"{rel}/probe.md"
            self.assertEqual(check_public.find_path_denylist_violations([probe]), [],
                             f"public root '{rel}/' is path-denied")
class ConfigRefusalReportingTests(unittest.TestCase):
    """A config layer that REFUSES to resolve must not take the guard down.

    Config discovery raises when no real ``config.yaml`` is reachable while a
    private overlay is mounted. This guard runs in pre-push; a traceback there is
    strictly worse than a report saying no identity was resolved, so the refusal is
    reported and the scan still runs (with zero config-derived tokens).
    """

    class _RaisingConfig:
        EXAMPLE_CONFIG = Path("/nonexistent/config.example.yaml")

        @staticmethod
        def config_path():
            raise RuntimeError("no config.yaml found and the example was refused")

        @staticmethod
        def candidate_name():                       # pragma: no cover — never reached
            raise AssertionError("identity must not be read from a refused config")

    def _patch(self):
        original = check_public._load_shared_config
        check_public._load_shared_config = lambda: self._RaisingConfig
        self.addCleanup(setattr, check_public, "_load_shared_config", original)

    def test_status_reports_no_identity_instead_of_raising(self):
        self._patch()
        status = check_public.config_identity_status()
        self.assertIn("no identity resolved", status)
        self.assertIn("RuntimeError", status)

    def test_identity_tokens_degrade_to_empty(self):
        self._patch()
        self.assertEqual(check_public._identity_tokens(self._RaisingConfig), set())
        # personal_tokens() still resolves (env + overlay file), it just gains
        # nothing from the config.
        self.assertIsInstance(check_public.personal_tokens(), list)

    def test_scan_still_runs_and_reports_the_refusal(self):
        self._patch()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tracked = _write_tree(root, {"README.md": "clean\n"})
            result = check_public.scan(root, tracked=tracked, tokens=[])
        self.assertTrue(result["ok"])
        self.assertIn("no identity resolved", result["config_status"])


class ExporterEndToEndTests(unittest.TestCase):
    """Run the real exporter, then assert the export is clean end-to-end."""

    # A token that ARMS the exporter's own gate without naming anybody: it
    # matches no path and no file content, so the guard still leans on structural
    # / path checks — the same "clean example tree stays green" path this test
    # always exercised.
    PROBE_TOKEN = "zz-exporter-e2e-probe-token"

    def setUp(self):
        # Deterministic AND armed. ``export()`` now refuses to run with zero
        # identity tokens (an unarmed final guard would call any tree safe to
        # publish), so simply popping the env var passes only in a maintainer
        # checkout that has a real config.yaml. CI has neither a config.yaml nor
        # the token secret, so popping it turned this repo's own CI red.
        # Forwarding a token that names nobody keeps the assertion identical in
        # every checkout.
        os.environ[check_public.TOKENS_ENV_VAR] = self.PROBE_TOKEN
        self.addCleanup(lambda: os.environ.pop(check_public.TOKENS_ENV_VAR, None))

    def test_export_survives_an_absolute_jobhunt_config_in_the_environment(self):
        """A maintainer with ``$JOBHUNT_CONFIG`` exported must still be able to publish.

        ``_run_guard`` forwards the environment wholesale to a guard whose ``cwd``
        is the freshly copied export. An inherited ABSOLUTE ``$JOBHUNT_CONFIG``
        then names the SOURCE checkout's config while the guard's own
        ``EXAMPLE_CONFIG`` resolves inside the export — the same file at two
        absolute paths. Path equality said "not the example", so ``Jordan`` and
        ``Rivers`` became personal-identity tokens and a clean tree failed with a
        hundred-odd hits on the toolkit's own documentation.
        """
        saved = os.environ.get("JOBHUNT_CONFIG")
        os.environ["JOBHUNT_CONFIG"] = str(REPO_ROOT / "config.example.yaml")

        def _restore():
            if saved is None:
                os.environ.pop("JOBHUNT_CONFIG", None)
            else:
                os.environ["JOBHUNT_CONFIG"] = saved

        self.addCleanup(_restore)
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "export"
            rc = export_public.export(dest, git_init=False, force=False)
        self.assertEqual(
            rc, 0,
            "the fictional example persona must never arm the guard, however "
            "$JOBHUNT_CONFIG is spelled")

    def test_export_passes_guard_and_excludes_private_trees(self):
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "export"
            rc = export_public.export(dest, git_init=False, force=False)
            self.assertEqual(rc, 0, "exporter+guard must pass on the clean example tree")

            copied = [p.relative_to(dest).as_posix()
                      for p in dest.rglob("*")
                      if p.is_file() and ".git/" not in p.relative_to(dest).as_posix()]

            # No private product trees leaked into the manifest.
            for bad in ("applications/", "interviews/", ".agents/inputs/"):
                offenders = [c for c in copied if c.startswith(bad)]
                self.assertEqual(offenders, [], f"{bad} leaked: {offenders}")

            # Per-skill private notes are pruned under either folder name; only
            # frontmatter-declared public skills are copied.
            for name in check_public.SKILL_NOTES_DIRNAMES:
                self.assertFalse([c for c in copied if f"/{name}/" in f"/{c}"])
            exported_skills = {
                p.parent.name for p in (dest / "skills").glob("*/SKILL.md")
            }
            self.assertEqual(exported_skills, set(export_public.public_skills()))

            # meta.yaml only under examples/; no stray docx/pdf outside examples/.
            for c in copied:
                if Path(c).name == "meta.yaml":
                    self.assertTrue(c.startswith("examples/"), c)
                if Path(c).suffix.lower() in (".docx", ".pdf"):
                    self.assertTrue(c.startswith("examples/"), c)

            # The public .gitignore anchors the overlay mount + private product
            # trees. Overlay-skill adapter names belong only in the checkout's
            # repository-local Git metadata, never in this exported file.
            # Compared against the ACTIVE RULES, not the raw text: the file's own
            # comments name the retired rules on purpose.
            rules = {ln.strip() for ln in (dest / ".gitignore").read_text().splitlines()
                     if ln.strip() and not ln.strip().startswith("#")}
            for needle in ("private/", "/applications/", "/interviews/"):
                self.assertIn(needle, rules)
            for gone in ("skills/job-search/profiles/*.yaml",
                         "skills/*/references_private",
                         "skills/*/references_private/"):
                self.assertNotIn(gone, rules)
            for name in check_public._overlay_skill_name_tokens(REPO_ROOT):
                for host in export_public.sync_skill_manifests.SYMLINK_HOSTS:
                    self.assertNotIn(f"/{host}/{name}", rules)
            self.assertFalse([r for r in rules if r.startswith("!")],
                             "a negation is back: an ignore glob with negations is "
                             "what let a personal filename sit under skills/")

            # PHASE 4 INVARIANT: no exported path — file OR symlink — reaches into
            # the overlay. Overlay-only runtime entries are repository-locally
            # ignored, so `git ls-files` never sees them and
            # _regenerate_symlinks only writes ../../skills/<public>.
            inbound = [p.relative_to(dest).as_posix() for p in dest.rglob("*")
                       if p.is_symlink() and "private/" in os.readlink(p)]
            self.assertEqual(inbound, [], f"symlinks into the overlay: {inbound}")

            # And a fresh directory-tree scan of the export is clean, too.
            scan_result = check_public.scan(root=dest, tokens=[])
            self.assertTrue(scan_result["ok"], scan_result["violations"])


if __name__ == "__main__":
    unittest.main()
