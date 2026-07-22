"""Synthetic provider conformance through the skill's vendored contract copy."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPT_DIR))

from _vendor.mail.contract.conformance import run_synthetic
from _vendor.mail.providers.outlook_graph.synthetic import conformance_fixture


class OutlookConformanceTests(unittest.TestCase):
    def test_outlook_graph_passes_synthetic_conformance(self):
        result = run_synthetic(conformance_fixture)
        self.assertEqual(result.failures, [])
        # The suite must actually exercise the safety surface, not vacuously pass.
        self.assertIn("no-send-surface", result.passed)
        self.assertIn("draft-evidence-tripwire", result.passed)
        self.assertIn("preflight-refuses-after-sent-reply", result.passed)
        self.assertIn("preflight-refuses-existing-draft", result.passed)
        self.assertTrue(
            any(name.startswith("send-endpoint-denied") for name in result.passed)
        )


if __name__ == "__main__":
    unittest.main()
