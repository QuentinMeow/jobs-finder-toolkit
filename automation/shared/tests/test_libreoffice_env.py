"""Tests for LibreOffice discovery and the no-launch sandbox preflight."""
from __future__ import annotations

import ctypes
import os
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from _canonical_imports import pin_shared_modules

pin_shared_modules()

import libreoffice_env  # noqa: E402


class CandidateResolutionTests(unittest.TestCase):
    def test_candidates_are_dynamic_and_include_both_path_commands(self):
        with mock.patch.dict(os.environ, {"JOBHUNT_SOFFICE": "/custom/soffice"}), \
                mock.patch.object(Path, "home", return_value=Path("/opt/example-home")):
            candidates = libreoffice_env.soffice_candidates()
        self.assertEqual(candidates[0], "/custom/soffice")
        self.assertEqual(
            candidates[1],
            "/opt/example-home/Applications/LibreOffice.app/Contents/MacOS/soffice",
        )
        self.assertEqual(candidates[-2:], ("soffice", "libreoffice"))

    def test_libreoffice_on_path_has_parity_with_soffice(self):
        def which(candidate: str):
            return "/usr/bin/libreoffice" if candidate == "libreoffice" else None

        with mock.patch.dict(os.environ, {}, clear=True), \
                mock.patch.object(libreoffice_env.shutil, "which", side_effect=which), \
                mock.patch.object(libreoffice_env.Path, "exists", return_value=False):
            self.assertEqual(libreoffice_env.find_soffice(), "/usr/bin/libreoffice")


class LaunchServicesProbeTests(unittest.TestCase):
    def _probe(self, result: int, *, marker: str | None = None):
        sandbox_check = mock.MagicMock(return_value=result)
        library = SimpleNamespace(sandbox_check=sandbox_check)
        environment = {} if marker is None else {"CODEX_SANDBOX": marker}
        with mock.patch.object(libreoffice_env.sys, "platform", "darwin"), \
                mock.patch.dict(os.environ, environment, clear=True), \
                mock.patch.object(libreoffice_env.ctypes, "CDLL", return_value=library):
            access = libreoffice_env.launchservices_access()
        self.assertEqual(
            sandbox_check.argtypes,
            (ctypes.c_int, ctypes.c_char_p, ctypes.c_int),
        )
        sandbox_check.assert_called_once()
        args = sandbox_check.call_args.args
        self.assertEqual(args[:3], (os.getpid(), b"mach-lookup", 2))
        self.assertIsInstance(args[3], ctypes.c_char_p)
        self.assertEqual(
            args[3].value,
            b"com.apple.coreservices.launchservicesd",
        )
        return access

    def test_non_darwin_is_not_affected(self):
        with mock.patch.object(libreoffice_env.sys, "platform", "linux"), \
                mock.patch.object(libreoffice_env.ctypes, "CDLL") as cdll:
            access = libreoffice_env.launchservices_access()
        self.assertIs(access, libreoffice_env.LaunchServicesAccess.NOT_APPLICABLE)
        cdll.assert_not_called()

    def test_zero_is_allowed(self):
        self.assertIs(
            self._probe(0, marker="seatbelt"),
            libreoffice_env.LaunchServicesAccess.ALLOWED,
        )

    def test_positive_is_denied(self):
        self.assertIs(
            self._probe(1),
            libreoffice_env.LaunchServicesAccess.DENIED,
        )

    def test_negative_is_unknown_without_exact_marker(self):
        self.assertIs(
            self._probe(-1, marker="seatbelt "),
            libreoffice_env.LaunchServicesAccess.UNKNOWN,
        )

    def test_negative_with_exact_codex_marker_is_denied(self):
        self.assertIs(
            self._probe(-1, marker="seatbelt"),
            libreoffice_env.LaunchServicesAccess.DENIED,
        )

    def test_unavailable_api_uses_only_the_exact_codex_marker(self):
        with mock.patch.object(libreoffice_env.sys, "platform", "darwin"), \
                mock.patch.dict(os.environ, {"CODEX_SANDBOX": "seatbelt"}, clear=True), \
                mock.patch.object(
                    libreoffice_env.ctypes, "CDLL", side_effect=AttributeError
                ):
            access = libreoffice_env.launchservices_access()
        self.assertIs(access, libreoffice_env.LaunchServicesAccess.DENIED)

    def test_override_cannot_bypass_denied_launchservices(self):
        denied = libreoffice_env.LaunchServicesAccess.DENIED
        with mock.patch.object(
                libreoffice_env, "find_soffice", return_value="/custom/soffice"), \
                mock.patch.object(
                    libreoffice_env, "launchservices_access", return_value=denied
                ):
            environment = libreoffice_env.libreoffice_environment()
        self.assertEqual(environment.executable, "/custom/soffice")
        self.assertFalse(environment.usable)

    def test_denied_diagnostic_states_which_checks_never_ran(self):
        diagnostic = libreoffice_env.launchservices_denied_diagnostic("/custom/soffice")
        for text in (
            "No LibreOffice process was started",
            "PDF conversion and one-page PDF checks did not run",
            "FAIL, not SKIP or PASS",
            "outside the Codex app sandbox",
            "JOBHUNT_SOFFICE only selects a LibreOffice binary",
        ):
            self.assertIn(text, diagnostic)


if __name__ == "__main__":
    unittest.main()
