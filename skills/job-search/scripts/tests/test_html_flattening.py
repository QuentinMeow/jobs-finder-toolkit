"""HTML -> plain text flattening, and the per-source entity encoding it depends on.

``common.strip_html`` produces the ``description`` every content gate reads, so the
order it applies is a correctness question, not a formatting one: decoding entities
BEFORE stripping tags turns an escaped ``&lt;`` in ordinary JD prose ("teams of
&lt; 12", "p99 &lt; 200ms") into a real ``<``, and ``<[^>]+>`` then deletes
everything up to the next ``>`` — the rest of the enclosing element.

The tests below pin both halves of the contract:

* single-encoded sources (Ashby, Lever, Workday, SmartRecruiters, Amazon, Apple and
  every aggregator) keep the whole element, including a sponsorship denial that
  happens to sit after a ``&lt;``; and
* Greenhouse ``content=true`` — the one DOUBLE entity-encoded source in the
  toolkit — still flattens to the same plain text, via the explicit
  ``entity_encoded=True`` opt-in at its two call sites.
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[1]
for _p in (_SCRIPTS, _SCRIPTS / "_vendor"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import posting_parsers as pp  # noqa: E402
from common import JobPosting, strip_html  # noqa: E402
from scoring import visa_ok  # noqa: E402

# One paragraph of single-encoded JD prose: a "<" written as the entity, and a
# sponsorship denial after it. This is the shape Lever/Ashby/Workday hand us.
_SINGLE_ENCODED = (
    "<p>You will work in teams of &lt; 12 people. "
    "Work authorization: we are unable to sponsor or transfer visas of any kind.</p>"
)
# The same body as Greenhouse content=true delivers it: entity-encoded a second
# time, so the tags are "&lt;p&gt;" and the prose entity is "&amp;lt;".
_DOUBLE_ENCODED = (
    "&lt;p&gt;You will work in teams of &amp;lt; 12 people. "
    "Work authorization: we are unable to sponsor or transfer visas of any kind."
    "&lt;/p&gt;"
)
_EXPECTED = ("You will work in teams of < 12 people. Work authorization: we are "
             "unable to sponsor or transfer visas of any kind.")


class SingleEncodedFlatteningTests(unittest.TestCase):
    def test_escaped_lt_does_not_eat_the_rest_of_the_element(self):
        self.assertEqual(strip_html(_SINGLE_ENCODED), _EXPECTED)

    def test_bare_comparison_operators_survive(self):
        self.assertEqual(
            strip_html("<li>Keep p99 &lt; 200ms and error rate &gt; 0.1%</li>"),
            "Keep p99 < 200ms and error rate > 0.1%")

    def test_real_tags_are_still_stripped(self):
        self.assertEqual(strip_html("<p>Hello <b>world</b></p>"), "Hello world")

    def test_entities_are_still_decoded(self):
        self.assertEqual(strip_html("<p>R&amp;D team &mdash; hiring</p>"),
                         "R&D team — hiring")


class VisaGateConsequenceTests(unittest.TestCase):
    """The gate consequence: an eaten denial reads as 'unclear' and is kept."""

    def _posting(self, raw_html: str) -> JobPosting:
        return JobPosting(source="lever", company="Example Corp",
                          title="Platform Engineer",
                          url="https://example.test/1",
                          description=strip_html(raw_html))

    def test_sponsorship_denial_survives_flattening(self):
        posting = self._posting(_SINGLE_ENCODED)
        profile = {"visa": {"needs_sponsorship": True, "policy": "exclude_negative"}}
        kept = visa_ok(posting, profile)
        self.assertEqual(posting.visa_label, "no")
        self.assertFalse(kept)


class ContentHashTests(unittest.TestCase):
    """Change detection must see an edit that lands after an escaped '<'."""

    def test_edit_after_an_escaped_lt_changes_the_hash(self):
        before = strip_html(_SINGLE_ENCODED)
        after = strip_html(_SINGLE_ENCODED.replace(
            "we are unable to sponsor or transfer visas of any kind",
            "we sponsor H-1B transfers and file PERM after 12 months"))
        self.assertNotEqual(pp.content_hash(before), pp.content_hash(after))

    def test_normalizer_version_is_declared_and_current(self):
        # Entity decoding moved to parse time and the normalizer stopped
        # re-stripping tags: that is a normalizer semantics change, so the
        # version must have moved past the v2 behaviour.
        self.assertGreaterEqual(pp.NORMALIZER_VERSION, 3)


class GreenhouseDoubleEncodingTests(unittest.TestCase):
    """The documented exception must keep working — and stay opt-in."""

    def test_double_encoded_body_flattens_to_the_same_text(self):
        self.assertEqual(strip_html(_DOUBLE_ENCODED, entity_encoded=True), _EXPECTED)

    def test_parser_applies_the_opt_in_for_greenhouse(self):
        payload = json.dumps({"jobs": [{
            "id": 7, "title": "Platform Engineer", "absolute_url": "https://x/7",
            "location": {"name": "Remote"}, "content": _DOUBLE_ENCODED}]}).encode()
        rows = pp.parse_greenhouse(payload)
        self.assertEqual(rows[0]["description"], _EXPECTED)

    def test_single_encoded_source_does_not_get_the_extra_decode(self):
        # Turning the opt-in on for a single-encoded body re-creates the defect;
        # this pins that the two paths are genuinely different.
        self.assertNotEqual(strip_html(_SINGLE_ENCODED, entity_encoded=True),
                            strip_html(_SINGLE_ENCODED))


if __name__ == "__main__":
    unittest.main()
