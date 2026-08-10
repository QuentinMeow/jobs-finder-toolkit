"""The bounded-phrase gate may never hide a phrase from its own scan.

`_bounded_phrase_matches` is the hot path of the whole filter pipeline, and the
gate in front of it exists to skip phrases whose scan cannot produce a match.
A gate that skips a phrase the scan WOULD have matched is not slow, it is wrong
— and wrong here means a written sponsorship refusal silently becoming `review`.

GH #231 proposes gating that scan on a sponsorship / visa / immigration signal
word. Five settled denials in `_SPONSOR_NEGATIVE` contain no such word, so that
gate demotes five confident refusals and no existing test notices. This suite is
the reason the shipped gate is derived from the phrase lists instead: it asserts
the derivation directly, phrase by phrase, and then asserts the property the
derivation is supposed to buy — gate on and gate off return identical results.

Run with (from the repo root):
    .venv/bin/python -m unittest discover automation/shared/tests
"""
from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

from _canonical_imports import pin_shared_modules

pin_shared_modules()   # subject imports must resolve under automation/shared/

SHARED_DIR = Path(__file__).resolve().parents[1]
if str(SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(SHARED_DIR))

import job_metadata  # noqa: E402
from job_metadata import (  # noqa: E402
    _BOUNDED_ALIEN_ALNUM_RE,
    _SPONSOR_NEGATIVE,
    _SPONSOR_POSITIVE,
    _bounded_phrase_matches,
    _bounded_phrase_pattern,
    _bounded_phrase_words,
    _bounded_word_set,
    assess_sponsorship,
)

# Every phrase tuple this module scans through the gate. Collected from the
# module rather than restated, so a tuple added later is covered on the day it
# is added rather than on the day someone remembers this file.
PHRASE_TUPLES = {
    name: value
    for name, value in vars(job_metadata).items()
    if name.isupper()
    and isinstance(value, (tuple, frozenset, set))
    and value
    and all(isinstance(item, str) and item for item in value)
    and name.startswith(("_SPONSOR_", "_TOTAL_", "_SALARY_"))
}
ALL_PHRASES = sorted({phrase for phrases in PHRASE_TUPLES.values()
                      for phrase in phrases})


class BoundedPhraseGateTests(unittest.TestCase):

    def test_the_module_actually_exposes_phrase_tuples(self):
        """A collector that silently found nothing would make this suite vacuous."""
        self.assertIn("_SPONSOR_NEGATIVE", PHRASE_TUPLES)
        self.assertIn("_SPONSOR_POSITIVE", PHRASE_TUPLES)
        self.assertGreaterEqual(len(ALL_PHRASES), 60)

    def test_every_phrase_passes_its_own_gate(self):
        """The derivation itself: a phrase's own words satisfy its own gate."""
        for phrase in ALL_PHRASES:
            with self.subTest(phrase=phrase):
                words = _bounded_word_set(phrase)
                self.assertIsNotNone(words)
                self.assertTrue(
                    _bounded_phrase_words(phrase) <= words,
                    f"the gate would skip {phrase!r} against its own text")

    def test_every_phrase_is_found_in_its_own_text_through_the_gate(self):
        """End to end, for all phrase tuples: gate on, the phrase is still found."""
        for name, phrases in sorted(PHRASE_TUPLES.items()):
            for phrase in sorted(phrases):
                with self.subTest(tuple=name, phrase=phrase):
                    text = f"before the phrase. {phrase}. after the phrase."
                    hits = _bounded_phrase_matches(text, [phrase])
                    self.assertEqual([hit[0] for hit in hits], [phrase])

    def test_every_phrase_survives_case_and_whitespace_variation(self):
        """The pattern folds case and stretches runs of space; the gate must too."""
        for phrase in ALL_PHRASES:
            variant = re.sub(r"\s+", "  ", phrase).upper()
            with self.subTest(phrase=phrase):
                hits = _bounded_phrase_matches(f"x {variant} y", [phrase])
                self.assertEqual([hit[0] for hit in hits], [phrase])

    def test_gate_on_and_gate_off_agree_on_every_phrase_in_every_tuple(self):
        """The property the derivation buys, asserted against the scan itself.

        ``words=frozenset()`` cannot be used to disable the gate (it would skip
        everything), so the ungated reference re-implements the scan directly
        from the same compiled patterns.
        """
        texts = [
            "we do not offer relocation or visa sponsorship.",
            "this role does not offer sponsorship.",
            "applicants must be us citizens only.",
            "gc only. permanent resident only for this role.",
            "visa sponsorship is available and we sponsor h-1b transfers.",
            "base salary range: competitive. total compensation includes ote.",
            "we sponsor employee learning programs and community events.",
            "citizenship is required for this position.",
            "you will build and operate a data platform for a distributed team.",
            "",
            "sponsorship",
            "…smart punctuation • bullets — dashes ’quotes’ café…",
        ]
        for name, phrases in sorted(PHRASE_TUPLES.items()):
            phrases = tuple(phrases)
            for text in texts:
                with self.subTest(tuple=name, text=text[:40]):
                    gated = [(phrase, match.span())
                             for phrase, match in _bounded_phrase_matches(
                                 text, phrases)]
                    ungated = [
                        (phrase, match.span())
                        for phrase in phrases
                        for match in _bounded_phrase_pattern(phrase).finditer(text)
                    ]
                    self.assertEqual(gated, ungated)

    def test_the_alien_codepoint_constant_matches_a_full_sweep(self):
        """Pinned by derivation, not by memory.

        The gate compares lowercased ASCII word runs, and exactly four non-ASCII
        codepoints are nevertheless matched by ``(?i)[a-z0-9]``. Their presence
        disables the gate. Sweeping the whole codepoint space here is what keeps
        the hardcoded constant honest across Python versions.
        """
        alnum = re.compile(r"[a-z0-9]", re.I)
        swept = {chr(cp) for cp in range(0x80, 0x110000) if alnum.match(chr(cp))}
        self.assertEqual(swept, {"İ", "ı", "ſ", "K"})
        for char in swept:
            with self.subTest(char=char):
                self.assertTrue(_BOUNDED_ALIEN_ALNUM_RE.search(char))
                self.assertIsNone(_bounded_word_set(f"a {char} b"))

    def test_ordinary_non_ascii_text_still_uses_the_gate(self):
        """Bullets, dashes and accents are separators, not gate-disabling."""
        for char in "•—’éßﬁ":
            with self.subTest(char=char):
                self.assertIsNotNone(_bounded_word_set(f"a {char} b"))

    def test_an_alien_codepoint_falls_back_to_the_exact_scan(self):
        text = "this role does not offer ſponsorship."
        self.assertIsNone(_bounded_word_set(text))
        # ``ſ`` reads as "s" to the pattern, so the phrase still matches and
        # the disabled gate must not stand in its way.
        hits = _bounded_phrase_matches(text, ("not offer sponsorship",))
        self.assertEqual([hit[0] for hit in hits], ["not offer sponsorship"])

    def test_overlapping_phrases_are_both_returned(self):
        """Why this is not one union alternation.

        A union ``finditer`` returns non-overlapping matches and takes the first
        alternative that fits, so it reports only the longer phrase here. Both
        reach the sponsorship evidence list today, so losing one would change
        ``evidence`` and ``rule_ids`` while looking like a pure speedup.
        """
        text = "this role does not offer sponsorship."
        phrases = ("not offer sponsorship", "does not offer sponsorship")
        hits = _bounded_phrase_matches(text, phrases)
        self.assertEqual([hit[0] for hit in hits], list(phrases))


class NoSignalCitizenshipDenialTests(unittest.TestCase):
    """The five denials a signal-word prefilter would silently demote.

    Each is a settled refusal that names no sponsorship, visa or immigration
    word anywhere in it. `exclude_negative` — the default policy — drops
    `no_match`, so demoting these to `review` would not be visible as an error;
    it would look like the classifier getting more cautious.
    """

    CASES = (
        "Applicants must be US citizens only.",
        "Permanent resident only for this role.",
        "GC only.",
        "Citizenship is required for this position.",
        "Must be a U.S. citizen.",
    )

    def test_none_of_them_contains_a_sponsorship_signal_word(self):
        signal = re.compile(
            r"\b(?:sponsor(?:ship|ing)?|visa|immigration|work authorization|"
            r"h-?1b|green card|perm)\b", re.I)
        for text in self.CASES:
            with self.subTest(text):
                self.assertIsNone(signal.search(text))

    def test_each_is_still_a_confident_refusal(self):
        for text in self.CASES:
            with self.subTest(text):
                assessment = assess_sponsorship(text)
                self.assertEqual(assessment["decision"], "no_match")
                self.assertEqual(assessment["verdict"], "unlikely")
                self.assertEqual(assessment["confidence"], "high")
                self.assertTrue(assessment["evidence"])


if __name__ == "__main__":
    unittest.main()
