from __future__ import annotations

import sys
import unittest
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPT_DIR))

from outlook_email import CLI_COMMANDS, build_parser


class CliPolicyTests(unittest.TestCase):
    def test_command_surface_is_draft_only(self):
        self.assertEqual(
            set(CLI_COMMANDS),
            {
                "doctor", "login", "logout", "inbox", "sent", "drafts", "review-window",
                "read", "match-application", "create-draft", "create-reply-draft",
            },
        )
        parser = build_parser()
        with redirect_stderr(StringIO()), self.assertRaises(SystemExit):
            parser.parse_args(["send"])
