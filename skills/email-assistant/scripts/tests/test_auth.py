from __future__ import annotations

import sys
import unittest
import json
from pathlib import Path
from unittest.mock import patch

SCRIPT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPT_DIR))

from _vendor.mail.providers.outlook_graph.auth import (
    AuthError,
    AuthManager,
    DELEGATED_SCOPES,
    OutlookSettings,
)

AUTH_MODULE = "_vendor.mail.providers.outlook_graph.auth"


class FakeKeyring:
    def __init__(self):
        self.values = {}

    def get_password(self, service, username):
        return self.values.get((service, username))

    def set_password(self, service, username, value):
        self.values[(service, username)] = value

    def delete_password(self, service, username):
        del self.values[(service, username)]


class OutlookSettingsTests(unittest.TestCase):
    def test_personal_account_settings_validate(self):
        account = "jordan.rivers" + chr(64) + "example.invalid"
        OutlookSettings(
            account=account,
            client_id="00000000-0000-0000-0000-000000000001",
        ).validate()

    def test_non_consumer_tenant_is_rejected(self):
        account = "jordan.rivers" + chr(64) + "example.invalid"
        with self.assertRaises(AuthError):
            OutlookSettings(
                account=account,
                client_id="00000000-0000-0000-0000-000000000001",
                tenant="organizations",
            ).validate()

    def test_scopes_are_exactly_readwrite_without_send(self):
        self.assertEqual(
            set(DELEGATED_SCOPES),
            {
                "https://graph.microsoft.com/User.Read",
                "https://graph.microsoft.com/Mail.ReadWrite",
            },
        )

    def test_device_login_and_refresh_use_keyring_state(self):
        account = "jordan.rivers" + chr(64) + "example.invalid"
        settings = OutlookSettings(
            account=account,
            client_id="00000000-0000-0000-0000-000000000001",
        )
        fake_keyring = FakeKeyring()
        login_responses = [
            {
                "device_code": "device-code",
                "user_code": "ABCD-EFGH",
                "message": "Use the Microsoft device page.",
                "interval": 1,
                "expires_in": 600,
            },
            {"error": "authorization_pending"},
            {"access_token": "access-1", "refresh_token": "refresh-1"},
        ]
        messages = []
        with (
            patch(f"{AUTH_MODULE}._keyring", return_value=fake_keyring),
            patch(f"{AUTH_MODULE}._post_form", side_effect=login_responses),
            patch(f"{AUTH_MODULE}.time.sleep"),
        ):
            token = AuthManager(settings).login(printer=messages.append)
        self.assertEqual(token, "access-1")
        self.assertEqual(messages, ["Use the Microsoft device page."])
        serialized = next(iter(fake_keyring.values.values()))
        self.assertEqual(json.loads(serialized)["refresh_token"], "refresh-1")

        with (
            patch(f"{AUTH_MODULE}._keyring", return_value=fake_keyring),
            patch(
                f"{AUTH_MODULE}._post_form",
                return_value={"access_token": "access-2", "refresh_token": "refresh-2"},
            ),
        ):
            refreshed = AuthManager(settings).access_token()
        self.assertEqual(refreshed, "access-2")
        serialized = next(iter(fake_keyring.values.values()))
        self.assertEqual(json.loads(serialized)["refresh_token"], "refresh-2")
