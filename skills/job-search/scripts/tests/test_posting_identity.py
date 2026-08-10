"""Identity + versioned URL-canonicalizer tests (store stage 2)."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import posting_identity as ident  # noqa: E402


class CanonicalizerTests(unittest.TestCase):
    def test_scheme_and_host_lowercased(self):
        a = ident.canonicalize_url("HTTPS://RemoteOK.com/remote-jobs/x")
        b = ident.canonicalize_url("https://remoteok.com/remote-jobs/x")
        self.assertEqual(a, b)

    def test_tracking_params_stripped(self):
        base = "https://jobs.example.com/p/123"
        withtrack = base + "?utm_source=li&gh_src=abc&ref=x&source=y&keep=1"
        self.assertEqual(ident.canonicalize_url(withtrack), base + "?keep=1")

    def test_fragment_and_trailing_slash_normalized(self):
        a = ident.canonicalize_url("https://x.com/a/b/#frag")
        b = ident.canonicalize_url("https://x.com/a/b")
        self.assertEqual(a, b)

    def test_missing_scheme_defaults_https(self):
        self.assertTrue(ident.canonicalize_url("x.com/a").startswith("https://"))

    def test_url_key_stable_under_tracking_noise(self):
        k1 = ident.url_key("https://x.com/p/9?utm_medium=email")
        k2 = ident.url_key("https://x.com/p/9")
        self.assertEqual(k1, k2)
        self.assertTrue(k1.startswith("url-"))

    def test_version_is_declared(self):
        self.assertIsInstance(ident.CANONICALIZER_VERSION, int)


class PlatformKeyTests(unittest.TestCase):
    def test_platform_keys_have_no_board_token(self):
        self.assertEqual(ident.gh_key("1234567"), "gh-1234567")
        self.assertEqual(ident.ashby_key("ABC-1"), "ashby-abc-1")
        self.assertEqual(ident.lever_key("uu-2"), "lever-uu-2")

    def test_workday_namespaced_by_company(self):
        self.assertEqual(ident.workday_key("NVIDIA", "JR1980360"),
                         "wd-nvidia-jr1980360")

    def test_identify_prefers_platform_id(self):
        row = {"source": "greenhouse", "native_id": "999", "url": "https://x/y"}
        key, strength = ident.identify(row, company_slug="examplecorp")
        self.assertEqual(key, "gh-999")
        self.assertEqual(strength, ident.STRONG)

    def test_identify_workday_uses_company_slug(self):
        row = {"source": "workday", "native_id": "R-42", "url": ""}
        key, strength = ident.identify(row, company_slug="acme")
        self.assertEqual(key, "wd-acme-r-42")
        self.assertEqual(strength, ident.STRONG)

    def test_identify_aggregator_url_key(self):
        row = {"source": "jobicy", "native_id": "5", "url": "https://jobicy.com/p/5"}
        key, strength = ident.identify(row, company_slug="")
        self.assertTrue(key.startswith("url-"))
        self.assertEqual(strength, ident.STRONG)

    def test_identify_content_key_is_weak(self):
        row = {"source": "themuse", "native_id": None, "url": "",
               "title": "SWE", "company_name": "GhostCo", "location": "Remote"}
        key, strength = ident.identify(row, company_slug="")
        self.assertTrue(key.startswith("ck-"))
        self.assertEqual(strength, ident.WEAK)

    def test_content_key_location_order_insensitive(self):
        a = ident.content_key("co", "SWE", ["NYC", "SF"])
        b = ident.content_key("co", "SWE", ["SF", "NYC"])
        self.assertEqual(a, b)

    def test_a_generic_listing_url_is_not_identity(self):
        """A board root is the SAME string for every row a source returns.

        RemoteOK can hand back its bare listing URL instead of a per-job
        permalink. Hashing it would give unrelated jobs one entity key, and the
        store builder folds one key into one entity — welding one job's title to
        another job's JD and dropping a posting with no trace.
        """
        for board in ("https://remoteok.com/remote-jobs/",
                      "https://remoteok.com/remote-jobs",
                      "https://boards.example.com/jobs",
                      "https://boards.example.com/careers/search",
                      "https://boards.example.com/"):
            self.assertFalse(ident.url_identifies_a_posting(board), board)
            self.assertIsNone(ident.url_key(board), board)

    def test_a_real_posting_url_still_keys_on_its_url(self):
        for posting in ("https://remoteok.com/remote-jobs/104221-backend-northwind",
                        "https://boards.example.com/jobs/4471",
                        "https://boards.example.com/viewjob?jk=a1b2c3",
                        "https://boards.example.com/jobs/northwind/staff-engineer"):
            self.assertTrue(ident.url_identifies_a_posting(posting), posting)
            self.assertTrue((ident.url_key(posting) or "").startswith("url-"), posting)

    def test_two_jobs_under_one_generic_url_do_not_share_a_key(self):
        """The precondition for the store's chimera: same URL, different jobs."""
        board = "https://remoteok.com/remote-jobs/"
        a = {"source": "remoteok", "native_id": "aa-1", "url": board,
             "title": "Senior Backend Engineer", "company_name": "Northwind Systems",
             "location": "Remote"}
        b = {"source": "remoteok", "native_id": "bb-2", "url": board,
             "title": "Staff Data Scientist", "company_name": "Larkspur Analytics",
             "location": "Remote"}
        key_a, strength_a = ident.identify(a, company_slug="northwind-systems")
        key_b, strength_b = ident.identify(b, company_slug="larkspur-analytics")
        self.assertNotEqual(key_a, key_b)
        # Falling through to the content key is the documented last resort, and it
        # is marked weak so nothing downstream mistakes it for a stable id.
        for key, strength in ((key_a, strength_a), (key_b, strength_b)):
            self.assertTrue(key.startswith("ck-"), key)
            self.assertEqual(strength, ident.WEAK)

    def test_new_source_platform_keys(self):
        for src, native, prefix in (("smartrecruiters", "744000", "sr"),
                                    ("amazon", "2851234", "amazon"),
                                    ("apple", "200591234", "apple"),
                                    ("meta", "a1b2c3", "meta")):
            row = {"source": src, "native_id": native, "url": "https://x/y"}
            key, strength = ident.identify(row, company_slug="")
            self.assertEqual(key, f"{prefix}-{native.lower()}")
            self.assertEqual(strength, ident.STRONG)


if __name__ == "__main__":
    unittest.main()
