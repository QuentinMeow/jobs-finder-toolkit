import sys
import unittest
from pathlib import Path

SHARED_DIR = Path(__file__).resolve().parents[1]
if str(SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(SHARED_DIR))

from location import classify_location, classify_locations  # noqa: E402

# A representative us_only policy with a couple of preferred metros.
_POLICY = {
    "metro": ["springfield", "fairview"],
    "allow_us_remote": True,
    "us_only": True,
}


class DistributedTagTests(unittest.TestCase):
    """A bare 'Distributed' location tag is unverified, not a US-remote match."""

    def test_bare_distributed_is_unknown_not_us_remote(self):
        self.assertEqual(classify_location("Distributed", _POLICY), "unknown")

    def test_distributed_hybrid_tag_is_unknown(self):
        self.assertEqual(
            classify_location("Distributed; Hybrid", _POLICY), "unknown")

    def test_distributed_does_not_grant_a_match(self):
        # The globally-pinned-role false positive: "Distributed" tag on a role
        # that is really a foreign city must not classify as a match.
        _, matched = classify_locations(["Distributed"], _POLICY)
        self.assertFalse(matched)

    def test_foreign_city_still_foreign(self):
        self.assertEqual(classify_location("Melbourne", _POLICY), "foreign")


class RemoteRegressionTests(unittest.TestCase):
    """Genuine remote / US signals must keep matching after the fix."""

    def test_explicit_remote_still_us_remote(self):
        self.assertEqual(classify_location("Remote", _POLICY), "us_remote")
        self.assertEqual(classify_location("Remote (US)", _POLICY), "us_remote")

    def test_country_level_us_still_us_remote(self):
        self.assertEqual(classify_location("United States", _POLICY), "us_remote")

    def test_preferred_metro_still_matches(self):
        self.assertEqual(classify_location("Springfield, ST", _POLICY), "metro")

    def test_worldwide_and_anywhere_remain_remote(self):
        self.assertEqual(classify_location("Anywhere", _POLICY), "us_remote")
        self.assertEqual(classify_location("Worldwide", _POLICY), "us_remote")


if __name__ == "__main__":
    unittest.main()
