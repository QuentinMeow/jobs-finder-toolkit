"""Tests for `check.py --rules` — the authoritative, generated gate dump.

Guards the contract that the dump (a) names every check group a FAIL can come
from, derived programmatically from the checker source, and (b) carries the key
numeric thresholds straight from the live constants (never a hand-written string
that could drift from the code).
"""

from __future__ import annotations

import inspect
import os
import subprocess
import sys
import unittest
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1]
REPO_ROOT = Path(__file__).resolve().parents[4]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import check  # noqa: E402


def _fail_capable_check_groups() -> set[str]:
    """Every module-level `check_*` function whose body can raise a FAIL.

    Derived from the source so a newly added checker that can FAIL but is missing
    from the `--rules` dump trips this test instead of silently going undocumented.
    """
    groups = set()
    for name, obj in vars(check).items():
        if name.startswith("check_") and inspect.isfunction(obj):
            if "c.fail(" in inspect.getsource(obj):
                groups.add(name)
    return groups


class RulesDumpTests(unittest.TestCase):
    def test_dump_names_every_fail_capable_check_group(self):
        documented = {name for name, _ in check.rule_groups()}
        missing = _fail_capable_check_groups() - documented
        self.assertEqual(
            missing, set(),
            f"--rules omits FAIL-producing check group(s): {sorted(missing)}")

    def test_warn_only_group_is_not_required(self):
        # check_drift only warns; the derivation must not demand it as a group.
        self.assertNotIn("check_drift", _fail_capable_check_groups())

    def test_group_keys_map_to_real_functions_or_schema(self):
        for name, _ in check.rule_groups():
            if name.startswith("check_"):
                self.assertTrue(
                    inspect.isfunction(getattr(check, name, None)),
                    f"rule group {name!r} is not a real checker function")

    def test_key_numeric_thresholds_come_from_constants(self):
        text = check.format_rules()
        b_lo, b_hi = check.BULLET_CHAR_RANGE
        d_lo, d_hi = check.DIRECT_BULLETS_RANGE
        p_lo, p_hi = check.BULLETS_PER_PROJECT
        cm_lo, cm_hi = check.COVER_MAIN_WORD_RANGE
        ct_lo, ct_hi = check.COVER_TOTAL_WORD_RANGE
        expected = [
            f"{b_lo}-{b_hi}",                       # bullet char range
            str(check.TITLE_MAX_CHARS),             # project title max
            f"{d_lo}-{d_hi}",                       # direct bullets/employer
            f"{p_lo}-{p_hi}",                       # bullets/project
            f"{cm_lo}-{cm_hi}",                     # cover main-paragraph words
            f"{ct_lo}-{ct_hi}",                     # cover body words
            str(check.COVER_MAIN_MIN_COUNT),        # min main paragraphs
            str(check.APPLICATION_SCHEMA_VERSION),  # meta.yaml schema version
            f"{check.RESUME_BOTTOM_BLANK_FAIL_IN:g}in",  # blank-bottom fail line
        ]
        for token in expected:
            self.assertIn(token, text, f"threshold {token!r} missing from --rules")

    def test_skill_semantics_and_aliases_are_present(self):
        text = check.format_rules()
        # Component-wise Weak matching + JD-mention requirement must be surfaced.
        self.assertIn("component-wise", text)
        self.assertRegex(text, r"REST/gRPC APIs")
        # Aliases are generated from the live alias table.
        for k, v in check._SKILL_ALIASES.items():
            self.assertIn(f"{k}={v}", text)

    def test_dump_is_compact(self):
        # Compact surface (vs reading the ~37 KB validator source).
        self.assertLess(len(check.format_rules().encode()), 3000)

    def test_cli_rules_flag_prints_and_exits_zero(self):
        env = dict(os.environ)
        env["JOBHUNT_CONFIG"] = str(REPO_ROOT / "config.example.yaml")
        proc = subprocess.run(
            [sys.executable, str(SCRIPTS / "check.py"), "--rules"],
            capture_output=True, text=True, env=env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout, check.format_rules())


if __name__ == "__main__":
    unittest.main()
