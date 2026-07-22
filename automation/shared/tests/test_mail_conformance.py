"""Contract + conformance suite: outlook_graph passes; broken providers fail."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import Any

SHARED = Path(__file__).resolve().parents[1]
if str(SHARED) not in sys.path:
    sys.path.insert(0, str(SHARED))

from mail.contract.conformance import run_live, run_synthetic  # noqa: E402
from mail.contract.interface import (  # noqa: E402
    CapabilityNotSupported,
    MailCapabilities,
    MailProvider,
)
from mail.contract.transport import AuditedHttpTransport, MailProviderError  # noqa: E402
from mail.providers.outlook_graph.provider import DraftOnlyGraphClient  # noqa: E402
from mail.providers.outlook_graph.route_policy import DraftOnlyRoutePolicy  # noqa: E402
from mail.providers.outlook_graph.synthetic import (  # noqa: E402
    SYNTHETIC_ACCOUNT,
    conformance_fixture,
)


class ContractShapeTests(unittest.TestCase):
    def test_contract_has_no_send_operation(self):
        send_like = [
            attr for attr in dir(MailProvider)
            if "send" in attr.lower() and "sender" not in attr.lower()
        ]
        self.assertEqual(send_like, [])

    def test_subclass_with_send_like_attribute_is_refused(self):
        with self.assertRaises(TypeError):
            type(
                "RogueProvider",
                (DraftOnlyGraphClient,),
                {"send_message": lambda self: None},
            )

    def test_unsupported_search_capability_fails_closed(self):
        provider = conformance_fixture().provider
        self.assertTrue(provider.capabilities().delta_sync)
        with self.assertRaises(CapabilityNotSupported):
            provider.search("interview")

    def test_transport_requires_a_route_policy(self):
        with self.assertRaises(MailProviderError):
            AuditedHttpTransport(None)
        with self.assertRaises(MailProviderError):
            AuditedHttpTransport(object())

    def test_transport_denies_and_audits_before_network(self):
        transport = AuditedHttpTransport(DraftOnlyRoutePolicy, provider="outlook_graph")
        with self.assertRaises(Exception):
            transport.request(
                "POST", "https://graph.microsoft.com/v1.0/me/sendMail", "token"
            )
        self.assertEqual(len(transport.audit_log), 1)
        record = transport.audit_log[0]
        self.assertEqual(record["outcome"], "denied")
        self.assertEqual(record["path"], "/v1.0/me/sendMail")
        # Metadata only: no url/query/body/subject fields in the audit record.
        self.assertEqual(
            set(record),
            {"ts", "provider", "method", "path", "outcome", "duration_ms"},
        )


class SyntheticConformanceTests(unittest.TestCase):
    def test_outlook_graph_passes(self):
        result = run_synthetic(conformance_fixture)
        self.assertEqual(result.failures, [])
        self.assertIn("draft-evidence-tripwire", result.passed)

    def test_provider_without_probes_fails(self):
        class NoProbePolicy:
            SEND_ENDPOINT_PROBES = ()

            @classmethod
            def assert_allowed(cls, method, url):
                return None

        def broken_fixture():
            fixture = conformance_fixture()
            fixture.provider.__class__ = type(
                "NoProbeClient", (DraftOnlyGraphClient,), {"route_policy": NoProbePolicy}
            )
            return fixture

        result = run_synthetic(broken_fixture)
        self.assertTrue(
            any("send-probes-declared" in failure for failure in result.failures)
        )

    def test_policy_allowing_send_endpoint_fails(self):
        class LeakyPolicy:
            SEND_ENDPOINT_PROBES = (
                ("POST", "https://graph.microsoft.com/v1.0/me/sendMail"),
            )

            @classmethod
            def assert_allowed(cls, method, url):
                return None  # allows everything, including the send probe

        def leaky_fixture():
            fixture = conformance_fixture()
            fixture.provider.__class__ = type(
                "LeakyClient", (DraftOnlyGraphClient,), {"route_policy": LeakyPolicy}
            )
            return fixture

        result = run_synthetic(leaky_fixture)
        self.assertTrue(
            any("send-endpoint-denied" in failure for failure in result.failures)
        )

    def test_provider_that_cannot_prove_the_tripwire_fails(self):
        class NoTripwireFixture:
            """Fixture whose backend never lies, so the fail-closed path is
            unobservable — conformance must treat that as a failure."""

            def __init__(self):
                self.inner = conformance_fixture()
                self.provider = self.inner.provider

            def __getattr__(self, name: str) -> Any:
                return getattr(self.inner, name)

            def force_non_draft_evidence(self) -> None:
                pass  # backend keeps returning isDraft: true

        result = run_synthetic(NoTripwireFixture)
        self.assertTrue(
            any("draft-evidence-tripwire" in failure for failure in result.failures)
        )
        honest = run_synthetic(conformance_fixture)
        self.assertIn("draft-evidence-tripwire", honest.passed)


class LiveModeShapeTests(unittest.TestCase):
    """Live mode logic exercised against the synthetic transport (no network)."""

    def test_live_run_is_read_only_and_passes(self):
        fixture = conformance_fixture()

        class AuditingSyntheticTransport:
            def __init__(self, inner):
                self.inner = inner
                self.audit_log = []

            def request(self, method, url, access_token, payload=None, headers=None):
                from urllib.parse import urlsplit

                self.audit_log.append(
                    {"method": method.upper(), "path": urlsplit(url).path}
                )
                return self.inner.request(method, url, access_token, payload, headers)

        fixture.provider.transport = AuditingSyntheticTransport(fixture.transport)
        result = run_live(fixture.provider)
        self.assertEqual(result.failures, [])
        self.assertIn("live-read-only-proof", result.passed)
        account = fixture.provider.verify_account()
        self.assertEqual(account.get("mail"), SYNTHETIC_ACCOUNT)

    def test_live_run_fails_on_observed_mutation(self):
        fixture = conformance_fixture()

        class MutatingTransport:
            def __init__(self, inner):
                self.inner = inner
                self.audit_log = [{"method": "POST", "path": "/v1.0/me/messages"}]

            def request(self, method, url, access_token, payload=None, headers=None):
                return self.inner.request(method, url, access_token, payload, headers)

        fixture.provider.transport = MutatingTransport(fixture.transport)
        result = run_live(fixture.provider)
        self.assertTrue(
            any("live-read-only-proof" in failure for failure in result.failures)
        )

    def test_capabilities_are_honest_for_outlook(self):
        caps = conformance_fixture().provider.capabilities()
        self.assertEqual(
            caps,
            MailCapabilities(read=True, drafts=True, delta_sync=True, search=False),
        )


if __name__ == "__main__":
    unittest.main()
