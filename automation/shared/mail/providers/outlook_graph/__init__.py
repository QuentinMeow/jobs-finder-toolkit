"""outlook_graph provider — Microsoft Graph, draft-capable, permanently send-less.

Read ``README.md`` in this folder before touching OAuth, permissions, or Graph
routes. Public surface: ``provider.DraftOnlyGraphClient`` (the MailProvider
implementation), ``route_policy.DraftOnlyRoutePolicy``, ``auth`` (device-code
OAuth + OS keyring), ``synthetic.conformance_fixture`` (generated fixture
mailbox for the conformance suite).
"""
