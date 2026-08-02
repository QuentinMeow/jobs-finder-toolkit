from __future__ import annotations

import sys
import unittest
import concurrent.futures
import json
import multiprocessing
import threading
import time
from pathlib import Path
from unittest.mock import patch

SCRIPT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPT_DIR))

from _vendor.mail.providers.outlook_graph.auth import (
    AuthError,
    AuthManager,
    DELEGATED_SCOPES,
    OutlookSettings,
    _oauth_cache_lock,
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


class RaceDetectingKeyring(FakeKeyring):
    def __init__(self):
        super().__init__()
        self._guard = threading.Lock()
        self.active_writers = 0
        self.max_active_writers = 0

    def set_password(self, service, username, value):
        with self._guard:
            self.active_writers += 1
            self.max_active_writers = max(
                self.max_active_writers, self.active_writers
            )
        try:
            time.sleep(0.02)
            super().set_password(service, username, value)
        finally:
            with self._guard:
                self.active_writers -= 1


class PersistThenFailKeyring(FakeKeyring):
    def set_password(self, service, username, value):
        super().set_password(service, username, value)
        raise RuntimeError("-25299, duplicate item")


def _hold_process_lock(cache_key, ready, release):
    with _oauth_cache_lock(cache_key):
        ready.set()
        release.wait(10)


def _await_process_lock(cache_key, attempting, acquired):
    attempting.set()
    with _oauth_cache_lock(cache_key):
        acquired.set()


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

    def test_concurrent_refreshes_serialize_rotating_keyring_writes(self):
        account = "jordan.rivers" + chr(64) + "example.invalid"
        settings = OutlookSettings(
            account=account,
            client_id="00000000-0000-0000-0000-000000000001",
        )
        fake_keyring = RaceDetectingKeyring()
        fake_keyring.values[(
            "jobs-finder-combined.outlook-email-assistant.oauth",
            settings.cache_key,
        )] = json.dumps({
            "account": account,
            "client_id": settings.client_id,
            "refresh_token": "refresh-0",
            "tenant": "consumers",
        })
        start = threading.Barrier(5)
        sequence_guard = threading.Lock()
        refresh_inputs = []

        def refresh(_url, values):
            with sequence_guard:
                refresh_inputs.append(values["refresh_token"])
                number = len(refresh_inputs)
            return {
                "access_token": f"access-{number}",
                "refresh_token": f"refresh-{number}",
            }

        def worker():
            start.wait()
            return AuthManager(settings).access_token()

        with (
            patch(f"{AUTH_MODULE}._keyring", return_value=fake_keyring),
            patch(f"{AUTH_MODULE}._post_form", side_effect=refresh),
            concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor,
        ):
            tokens = list(executor.map(lambda _index: worker(), range(5)))

        self.assertEqual(set(tokens), {f"access-{index}" for index in range(1, 6)})
        self.assertEqual(fake_keyring.max_active_writers, 1)
        self.assertEqual(
            refresh_inputs,
            [f"refresh-{index}" for index in range(5)],
        )

    def test_refresh_lock_serializes_separate_processes(self):
        context = multiprocessing.get_context("spawn")
        ready = context.Event()
        release = context.Event()
        attempting = context.Event()
        acquired = context.Event()
        cache_key = "process-race@example.invalid"
        holder = context.Process(
            target=_hold_process_lock, args=(cache_key, ready, release)
        )
        waiter = context.Process(
            target=_await_process_lock, args=(cache_key, attempting, acquired)
        )
        holder.start()
        try:
            self.assertTrue(ready.wait(10), "holder never acquired OAuth lock")
            waiter.start()
            self.assertTrue(attempting.wait(10), "waiter process never started")
            self.assertFalse(
                acquired.wait(0.2), "second process bypassed the OAuth lock"
            )
            release.set()
            self.assertTrue(acquired.wait(10), "waiter never acquired released lock")
        finally:
            release.set()
            holder.join(10)
            if waiter.pid is not None:
                waiter.join(10)
            for process in (holder, waiter):
                if process.is_alive():
                    process.terminate()
                    process.join(5)
        self.assertEqual(holder.exitcode, 0)
        self.assertEqual(waiter.exitcode, 0)

    def test_keyring_write_error_is_idempotent_only_after_exact_readback(self):
        account = "jordan.rivers" + chr(64) + "example.invalid"
        settings = OutlookSettings(
            account=account,
            client_id="00000000-0000-0000-0000-000000000001",
        )
        fake_keyring = PersistThenFailKeyring()
        with patch(f"{AUTH_MODULE}._keyring", return_value=fake_keyring):
            AuthManager(settings)._save_refresh_token("refresh-1")
        serialized = next(iter(fake_keyring.values.values()))
        self.assertEqual(json.loads(serialized)["refresh_token"], "refresh-1")

    def test_keyring_write_error_with_stale_readback_still_fails(self):
        account = "jordan.rivers" + chr(64) + "example.invalid"
        settings = OutlookSettings(
            account=account,
            client_id="00000000-0000-0000-0000-000000000001",
        )
        fake_keyring = FakeKeyring()
        fake_keyring.set_password = lambda *_args: (_ for _ in ()).throw(
            RuntimeError("-25299, duplicate item")
        )
        with (
            patch(f"{AUTH_MODULE}._keyring", return_value=fake_keyring),
            self.assertRaisesRegex(AuthError, "could not save OAuth state"),
        ):
            AuthManager(settings)._save_refresh_token("refresh-1")
