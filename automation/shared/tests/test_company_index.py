"""The company index: one test per lint rule, each PLANTING the defect it catches.

Run with (from the repo root):
    .venv/bin/python -m unittest discover -s automation/shared/tests

A lint rule with no failing input is a rule nobody has ever seen fire, so every
test here builds an index that is clean except for the one thing under test and
asserts the finding names it. The clean-baseline test at the top is what makes the
rest meaningful: it proves the fixtures are otherwise silent, so a finding really
does come from the planted defect.

Some tests exist because of a specific failure rather than a rule:

  * ``test_boolean_key_is_a_finding`` — PyYAML resolves plain scalar keys, so an
    unquoted ``on:``/``no:``/``y:`` key is a Python ``bool`` before any regex sees a
    string. Same class of bug that forced ``review_gate._LedgerLoader``;
  * ``test_lowercase_truncation_alias_is_a_finding`` — the shape of a reproduced
    false positive: a four-letter alias that is an ordinary word matched a CODE
    COMMENT that used that word, because the advisory detector substring-matches
    over the whole added-lines blob.

Four are GUARDS, named for what they protect rather than for the rule they test,
because each pins a rule that was implemented, measured against real data, and then
narrowed or withdrawn — and a future agent tightening this linter would otherwise
reinstate it:

  * ``test_short_abbreviation_alias_is_not_a_finding`` — no minimum alias length;
  * ``test_display_cased_short_form_alias_is_not_a_finding`` — the truncation rule
    fires on ALL-LOWERCASE aliases only;
  * ``test_short_display_name_is_not_a_finding`` — neither alias rule touches
    ``display``;
  * ``test_stop_list_holds_no_vocabulary_new_to_this_repo`` — a stop-list word that
    is new to the public tree BLINDS the advisory detector to any employer of that
    name, because the detector permanently subtracts names already in the tree.

Every fixture is fictional (``acme-*``, ``Acme *``); nothing here reads the owner's
index or any file at all except the temp files two tests write.
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

import yaml

SHARED = Path(__file__).resolve().parents[1]
if str(SHARED) not in sys.path:
    sys.path.insert(0, str(SHARED))

import company_index as ci  # noqa: E402


def entry(display: str = "Acme Labs", **overrides) -> dict:
    """A valid entry body; pass a field to break exactly one thing."""
    body = {"display": display, "kind": "employer"}
    body.update(overrides)
    return body


def subjects(raw) -> list[str]:
    return [subject for subject, _ in ci.lint(raw)]


def messages(raw) -> str:
    return "\n".join(message for _, message in ci.lint(raw))


class CleanBaselineTests(unittest.TestCase):
    """Without this, every other test could be passing for the wrong reason."""

    def test_a_well_formed_index_lints_clean(self):
        raw = {
            "acme-labs": entry("Acme Labs", aliases=["Acme Labs Inc.", "Acme Research"]),
            "acme-cloud": entry("Acme Cloud", kind="employer", parent="acme-labs"),
            "acme-screening": entry("Acme Screening Partners", kind="interview_vendor"),
        }
        self.assertEqual(ci.lint(raw), [])

    def test_an_absent_and_an_empty_index_are_clean(self):
        self.assertEqual(ci.lint(None), [])
        self.assertEqual(ci.lint({}), [])


class KeyShapeTests(unittest.TestCase):

    def test_boolean_key_is_a_finding(self):
        """The YAML 1.1 trap: an unquoted ``on:`` key is a bool, not a string."""
        raw = yaml.safe_load("on:\n  display: Acme On\n  kind: employer\n")
        self.assertIn(True, raw, "precondition: PyYAML must have typed the key as a bool")
        self.assertIn("top-level keys must be strings", messages(raw))
        self.assertIn("True", subjects(raw))

    def test_every_yaml_boolean_spelling_is_caught(self):
        for spelling in ("on", "off", "yes", "no", "y", "n"):
            with self.subTest(spelling=spelling):
                raw = yaml.safe_load(f"{spelling}:\n  display: Acme\n  kind: employer\n")
                if isinstance(next(iter(raw)), str):
                    continue          # this PyYAML does not type that spelling
                self.assertIn("top-level keys must be strings", messages(raw))

    def test_key_shape_is_enforced(self):
        raw = {"Acme_Labs": entry()}
        self.assertIn("key must match", messages(raw))

    def test_non_mapping_entry_is_a_finding(self):
        raw = {"acme-labs": "Acme Labs"}
        self.assertIn("entry must be a mapping", messages(raw))

    def test_non_mapping_file_is_a_finding(self):
        findings = ci.lint(["acme-labs"])
        self.assertEqual([f[0] for f in findings], [ci.FILE_SUBJECT])
        self.assertIn("must be a mapping of key -> entry", findings[0][1])


class FieldTests(unittest.TestCase):

    def test_missing_display_is_a_finding(self):
        raw = {"acme-labs": {"kind": "employer"}}
        self.assertIn("display is required", messages(raw))

    def test_blank_display_is_a_finding(self):
        raw = {"acme-labs": entry("   ")}
        self.assertIn("display is required", messages(raw))

    def test_unknown_kind_is_a_finding(self):
        raw = {"acme-labs": entry(kind="vendor")}
        self.assertIn("kind must be one of", messages(raw))

    def test_missing_kind_is_a_finding(self):
        raw = {"acme-labs": {"display": "Acme Labs"}}
        self.assertIn("kind must be one of", messages(raw))

    def test_unknown_field_is_a_finding(self):
        """A typo'd ``alias:`` silently drops that employer from the detector."""
        raw = {"acme-labs": entry(alias=["Acme Research"])}
        self.assertIn("unknown field(s): alias", messages(raw))


class ParentTests(unittest.TestCase):

    def test_dangling_parent_is_a_finding(self):
        raw = {"acme-cloud": entry("Acme Cloud", parent="acme-labs")}
        self.assertIn("is not a key in this index", messages(raw))

    def test_self_parent_is_a_finding(self):
        raw = {"acme-labs": entry(parent="acme-labs")}
        self.assertIn("cannot be its own parent", messages(raw))

    def test_parent_cycle_is_a_finding(self):
        raw = {
            "acme-labs": entry("Acme Labs", parent="acme-cloud"),
            "acme-cloud": entry("Acme Cloud", parent="acme-labs"),
        }
        text = messages(raw)
        self.assertIn("parent chain forms a cycle", text)
        self.assertEqual(text.count("cycle"), 1, "one finding per cycle, not per member")

    def test_a_resolvable_parent_chain_is_clean(self):
        raw = {
            "acme-labs": entry("Acme Labs"),
            "acme-cloud": entry("Acme Cloud", parent="acme-labs"),
            "acme-edge": entry("Acme Edge Systems", parent="acme-cloud"),
        }
        self.assertEqual(ci.lint(raw), [])


class AliasTests(unittest.TestCase):

    def test_shared_alias_is_a_finding(self):
        raw = {
            "acme-labs": entry("Acme Labs", aliases=["Acme Research"]),
            "acme-cloud": entry("Acme Cloud", aliases=["acme research"]),
        }
        self.assertIn("is already claimed by", messages(raw))

    def test_alias_colliding_with_a_display_is_a_finding(self):
        raw = {
            "acme-labs": entry("Acme Labs"),
            "acme-cloud": entry("Acme Cloud", aliases=["ACME LABS"]),
        }
        self.assertIn("is another entry's display name", messages(raw))

    def test_alias_colliding_with_a_key_is_a_finding(self):
        raw = {
            "acme-labs": entry("Acme Labs"),
            "acme-cloud": entry("Acme Cloud", aliases=["acme-labs"]),
        }
        self.assertIn("is another entry's key", messages(raw))

    def test_alias_duplicated_within_one_entry_is_a_finding(self):
        raw = {"acme-labs": entry(aliases=["Acme Research", "acme research"])}
        self.assertIn("is listed twice in this entry", messages(raw))

    def test_aliases_must_be_a_list(self):
        raw = {"acme-labs": entry(aliases="Acme Research")}
        self.assertIn("aliases must be a list", messages(raw))

    def test_empty_alias_is_a_finding(self):
        raw = {"acme-labs": entry(aliases=["  ", 7])}
        self.assertEqual(messages(raw).count("alias must be a non-empty string"), 2)

    def test_lowercase_truncation_alias_is_a_finding(self):
        """Rule 1, and the shape of the reproduced false positive.

        Every measured offender was an all-lowercase shortening of a dotted or
        two-word name, carried through from a log that stores aliases normalized.
        The detector's test is ``n.lower() in added`` over the whole added-lines
        blob, so a bare token matches a CODE COMMENT that merely uses that word —
        and the baseline subtraction does not save the FIRST diff to introduce it
        into the public tree.
        """
        for display, alias in (("Acme.ai", "acme"), ("Acme Labs", "acme"),
                               ("AcmeWorks", "acme")):
            with self.subTest(display=display, alias=alias):
                raw = {"acme-labs": entry(display, aliases=[alias])}
                self.assertIn("single-token shortening of its own display name",
                              messages(raw))

    def test_display_cased_short_form_alias_is_not_a_finding(self):
        """GUARD — rule 1 must stay restricted to ALL-LOWERCASE aliases.

        Without the lowercase condition the rule rejected a legitimate alias in a
        real index: a display-cased first word of a two-word employer name, which is
        exactly the short form a human writes and which a ``company:`` string may
        genuinely carry. Dropping it would leave that application unkeyed. The
        offenders are log-normalization artifacts; a spelling a human typed is not.
        """
        raw = {
            "acme-health": entry("AcmeHealth Systems", aliases=["AcmeHealth"]),
            "acme-labs": entry("Acme Labs", aliases=["Acme"]),
        }
        self.assertEqual(ci.lint(raw), [])

    def test_ordinary_word_alias_is_a_finding(self):
        """Rule 2 — a generic word that is NOT a truncation of the display."""
        raw = {"acme-labs": entry("Acme Labs", aliases=["canonical"])}
        self.assertIn("generic word this repository already uses", messages(raw))

    def test_ordinary_word_alias_is_caught_in_display_casing(self):
        """Aliases are display-cased, and the detector lowercases at comparison."""
        raw = {"acme-labs": entry("Acme Labs", aliases=["Canonical"])}
        self.assertIn("generic word this repository already uses", messages(raw))

    def test_short_abbreviation_alias_is_not_a_finding(self):
        """GUARD — do not reintroduce a minimum-alias-length rule.

        One was implemented, measured against a real index, and withdrawn: length 5
        destroyed a three-letter divisional acronym and a three-character ampersand
        initialism (both from the richest alias source in the repo, and neither
        capable of colliding with ordinary code) while still missing two
        five-character ordinary-word offenders. Short is not the problem; ordinary
        is. If this test fails, the rule was re-broken, not tightened.
        """
        raw = {
            "acme-cloud": entry("Acme Cloud Services", aliases=["ACS"]),
            "acme-labs": entry("Acme & Beacon Labs", aliases=["A&B"]),
        }
        self.assertEqual(ci.lint(raw), [])

    def test_short_display_name_is_not_a_finding(self):
        """GUARD — both alias rules apply to aliases ONLY.

        A short or generic display name is the employer's real name: it cannot be
        lengthened or dropped without lying, and in practice a real name is already
        somewhere in the public tree and so is permanently subtracted by the
        detector's baseline grep at ``review_gate.py:470-471``.
        """
        raw = {"acme-index": entry("Index", aliases=["Acme Index Systems"])}
        self.assertIn("index", ci.ALIAS_STOP_LIST,
                      "precondition: the same word IS stop-listed as an alias")
        self.assertEqual(ci.lint(raw), [])

    def test_a_multi_token_alias_is_never_stop_listed(self):
        """Only a bare token can collide with ordinary prose or code."""
        raw = {"acme-labs": entry("Acme Labs", aliases=["Canonical Acme Group"])}
        self.assertEqual(ci.lint(raw), [])

    def test_stop_list_tokens_are_shaped_like_vocabulary(self):
        """Leak guard on the list itself: it must read as generic vocabulary.

        Bare lowercase alphabetic tokens only — no punctuation, no digits, nothing
        with the shape of a company's legal name.
        """
        for token in ci.ALIAS_STOP_LIST:
            with self.subTest(token=token):
                self.assertTrue(token.isalpha() and token.islower(), token)

    def test_stop_list_holds_no_vocabulary_new_to_this_repo(self):
        """GUARD — a stop-list entry must be a word this repo ALREADY uses.

        Publishing a word here puts it in the public tree, and the detector
        permanently subtracts every name already in the public tree
        (``review_gate.py:470-471``). So a token that is NEW to this repo would
        blind the detector to any employer of that name, while suppressing a false
        positive this repo's own diffs could not produce anyway. A ~620-token
        English dictionary was tried and withdrawn for exactly that reason: 149 of
        its tokens were new to the tree.

        ``automation/`` and ``skills/`` are scanned because both always ship in the
        public export, so this assertion holds in an exported clone too.
        """
        repo = SHARED.parents[1]
        wanted = {".py", ".md", ".yaml", ".yml", ".txt", ".json", ".sh"}
        chunks = []
        for base in ("automation", "skills"):
            for path in (repo / base).rglob("*"):
                if (path.is_file() and path.suffix in wanted
                        and "__pycache__" not in path.parts):
                    chunks.append(path.read_text(encoding="utf-8", errors="ignore").lower())
        blob = "\n".join(chunks)
        new_words = sorted(t for t in ci.ALIAS_STOP_LIST if t not in blob)
        self.assertEqual(new_words, [], "these tokens are new vocabulary — publishing "
                                        "them would blind the advisory leak detector")


class LoadTests(unittest.TestCase):

    def _write(self, text: str) -> Path:
        tmp = Path(tempfile.mkdtemp(prefix="company-index-"))
        self.addCleanup(lambda: [p.unlink() for p in tmp.iterdir()] and tmp.rmdir())
        path = tmp / "_index.yaml"
        path.write_text(text, encoding="utf-8")
        return path

    def test_absent_file_loads_as_an_empty_index(self):
        self.assertEqual(ci.load(Path("/nonexistent/_index.yaml")), {})

    def test_malformed_yaml_propagates(self):
        path = self._write("acme-labs: [unclosed\n")
        with self.assertRaises(yaml.YAMLError):
            ci.load(path)

    def test_load_builds_entries(self):
        path = self._write(
            "acme-labs:\n"
            "  display: Acme Labs\n"
            "  aliases: [Acme Labs Inc.]\n"
            "  kind: employer\n"
            "acme-cloud:\n"
            "  display: Acme Cloud\n"
            "  kind: employer\n"
            "  parent: acme-labs\n"
        )
        index = ci.load(path)
        self.assertEqual(sorted(index), ["acme-cloud", "acme-labs"])
        self.assertEqual(index["acme-labs"].aliases, ("Acme Labs Inc.",))
        self.assertEqual(index["acme-cloud"].parent, "acme-labs")
        self.assertIsNone(index["acme-labs"].parent)

    def test_from_raw_drops_unusable_rows_rather_than_guessing(self):
        raw = {True: {"display": "Acme On"}, "acme-labs": entry(), "acme-x": "text"}
        self.assertEqual(sorted(ci.from_raw(raw)), ["acme-labs"])


class ResolveTests(unittest.TestCase):

    def setUp(self) -> None:
        self.index = ci.from_raw({
            "acme-labs": entry("Acme Labs", aliases=["Acme Labs Inc.", "Acme Research"]),
            "acme-cloud": entry("Acme Cloud"),
        })

    def test_key_display_and_alias_all_resolve_case_insensitively(self):
        for raw in ("acme-labs", "ACME-LABS", "Acme Labs", "acme labs",
                    "Acme Labs Inc.", "  acme   research  "):
            with self.subTest(raw=raw):
                self.assertEqual(ci.resolve(self.index, raw), "acme-labs")

    def test_an_unknown_string_abstains(self):
        """No suffix stripping and no fuzzy fallback: abstaining is the contract."""
        for raw in ("Acme", "Acme Labs Ltd.", "Acme Lab", "", "   "):
            with self.subTest(raw=raw):
                self.assertIsNone(ci.resolve(self.index, raw))


if __name__ == "__main__":
    unittest.main()
