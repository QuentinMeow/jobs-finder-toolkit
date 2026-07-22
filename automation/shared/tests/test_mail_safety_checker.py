"""Folder-walking mail-safety checker: real tree passes, planted fixtures fail.

The send-capable "provider" fixtures live INSIDE these tests (materialized into
a temp dir per run) — never shipped as a real provider folder.
"""
from __future__ import annotations

import itertools
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

SHARED = Path(__file__).resolve().parents[1]
if str(SHARED) not in sys.path:
    sys.path.insert(0, str(SHARED))

from mail.check_mail_safety import (  # noqa: E402
    check_consumer_dir,
    check_providers_tree,
)

_UNIQUE = itertools.count()

# A minimal provider that must PASS the checker (guards against false positives).
_CLEAN_POLICY = textwrap.dedent(
    '''
    """Minimal draft-only policy for the checker's own tests."""
    class CleanPolicy:
        SEND_ENDPOINT_PROBES = (
            ("POST", "https://mail.example.com/v1/sendMail"),
        )

        @classmethod
        def assert_allowed(cls, method, url):
            if method.upper() != "GET":
                raise RuntimeError("denied")
    '''
)


def _write_tree(root: Path, files: dict[str, str]) -> Path:
    """Materialize a package tree; returns the providers root."""
    package = root / f"vmailpkg{next(_UNIQUE)}"
    defaults = {
        "__init__.py": "",
        "providers/__init__.py": "",
    }
    for relative, content in {**defaults, **files}.items():
        path = package / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(content), encoding="utf-8")
        init = path.parent / "__init__.py"
        if not init.exists():
            init.write_text("", encoding="utf-8")
    return package / "providers"


class MailSafetyCheckerTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_real_provider_tree_and_consumer_pass(self):
        self.assertEqual(check_providers_tree(), [])
        repo_root = SHARED.parents[1]
        self.assertEqual(
            check_consumer_dir(repo_root / "skills/email-assistant/scripts"), []
        )

    def test_clean_fixture_provider_passes(self):
        providers = _write_tree(self.root, {
            "providers/cleanmail/route_policy.py": _CLEAN_POLICY,
            "providers/cleanmail/provider.py": '''
                """Reads messages only."""
                def list_inbox(limit=10):
                    return []
            ''',
        })
        self.assertEqual(check_providers_tree(providers), [])

    def test_planted_send_capable_provider_fails(self):
        """The acceptance fixture: a provider that CAN send must be caught."""
        providers = _write_tree(self.root, {
            "providers/sendful/route_policy.py": '''
                class OpenPolicy:
                    SEND_ENDPOINT_PROBES = (
                        ("POST", "https://mail.example.com/v1/messages/send"),
                    )

                    @classmethod
                    def assert_allowed(cls, method, url):
                        return None  # allows everything, including send
            ''',
            "providers/sendful/provider.py": '''
                API_SCOPES = ("https://graph.example.com/Mail.Send",)

                def deliver(message):
                    return post("/me/sendMail", message)
            ''',
        })
        errors = check_providers_tree(providers)
        joined = "\n".join(errors)
        self.assertIn("ALLOWED send/mutation endpoint", joined)  # probe passed policy
        self.assertTrue(  # Mail.Send scope string + /sendMail route in provider.py
            any("provider.py" in e and "banned sending pattern" in e for e in errors)
        )
        self.assertIn("scope literal 'API_SCOPES' has no registered pin", joined)

    def test_send_named_function_fails(self):
        providers = _write_tree(self.root, {
            "providers/fnmail/route_policy.py": _CLEAN_POLICY,
            "providers/fnmail/provider.py": '''
                def send_message(message):
                    return None
            ''',
        })
        errors = check_providers_tree(providers)
        self.assertTrue(any("banned sending pattern" in e for e in errors))

    def test_sdk_import_fails(self):
        providers = _write_tree(self.root, {
            "providers/sdkmail/route_policy.py": _CLEAN_POLICY,
            "providers/sdkmail/provider.py": '''
                import googleapiclient.discovery

                def build_client():
                    return googleapiclient.discovery.build("gmail", "v1")
            ''',
        })
        errors = check_providers_tree(providers)
        self.assertTrue(any("banned import" in e for e in errors))

    def test_transport_bypass_import_fails(self):
        providers = _write_tree(self.root, {
            "providers/httpmail/route_policy.py": _CLEAN_POLICY,
            "providers/httpmail/provider.py": '''
                import requests

                def fetch(url):
                    return requests.get(url)
            ''',
        })
        errors = check_providers_tree(providers)
        self.assertTrue(any("banned import" in e for e in errors))

    def test_cross_provider_import_fails(self):
        providers = _write_tree(self.root, {
            "providers/alpha/route_policy.py": _CLEAN_POLICY,
            "providers/alpha/provider.py": '''
                from ..beta import provider as beta_provider
            ''',
            "providers/beta/route_policy.py": _CLEAN_POLICY,
            "providers/beta/provider.py": "VALUE = 1\n",
        })
        errors = check_providers_tree(providers)
        self.assertTrue(any("cross-provider import" in e for e in errors))

    def test_missing_route_policy_fails(self):
        providers = _write_tree(self.root, {
            "providers/bare/provider.py": "VALUE = 1\n",
        })
        errors = check_providers_tree(providers)
        self.assertTrue(any("missing route_policy.py" in e for e in errors))

    def test_outlook_scope_drift_fails(self):
        providers = _write_tree(self.root, {
            "providers/outlook_graph/route_policy.py": _CLEAN_POLICY,
            "providers/outlook_graph/auth.py": '''
                DELEGATED_SCOPES = (
                    "https://graph.microsoft.com/User.Read",
                    "https://graph.microsoft.com/Mail.ReadWrite",
                    "https://graph.microsoft.com/Files.ReadWrite",
                )
            ''',
        })
        errors = check_providers_tree(providers)
        self.assertTrue(
            any("pinned scope literal 'DELEGATED_SCOPES' changed" in e for e in errors)
        )

    def test_consumer_cli_surface_pin(self):
        scripts = self.root / "scripts"
        scripts.mkdir()
        (scripts / "outlook_email.py").write_text(
            'CLI_COMMANDS = ("doctor", "login", "transmit")\n', encoding="utf-8"
        )
        errors = check_consumer_dir(scripts)
        self.assertTrue(any("CLI command surface changed" in e for e in errors))


if __name__ == "__main__":
    unittest.main()
