"""The contract's ONE audited HTTP transport + the route-allowlist base class.

The primary safety control (design/raw-data-layer/03-provider-interfaces.md
§2b): every provider routes ALL mail-API network I/O through this single
chokepoint; each provider ships a :class:`RoutePolicy` enumerating allowed
method+path shapes, so send endpoints are structurally unreachable. Raw
stdlib ``urllib`` only — provider SDKs are banned inside provider folders
because a runtime-generated API surface cannot be statically bounded.

Audit log: every request attempt is recorded in memory on the transport
(``.audit_log``) and, when a sink is configured (``audit_path=`` or the
``JOBHUNT_MAIL_AUDIT_LOG`` environment variable), appended as JSON lines.
A record holds timestamp, provider, HTTP method, URL *path*, outcome, and
duration only — NEVER query strings, headers, payloads, message bodies, or
subjects.
"""
from __future__ import annotations

import abc
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, ClassVar
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from .interface import MailProviderError

AUDIT_LOG_ENV = "JOBHUNT_MAIL_AUDIT_LOG"


class TransportError(MailProviderError):
    """The HTTP request failed (network, HTTP status, or malformed response)."""


class RoutePolicy(abc.ABC):
    """Per-provider route allowlist enforced before any network I/O.

    Subclasses enumerate allowed method+path shapes and MUST declare
    ``SEND_ENDPOINT_PROBES`` — that provider's send (and other must-deny
    mutation) endpoints. The conformance suite and the folder-walking safety
    checker probe the policy against every probe and fail on any pass.
    """

    #: (method, url) pairs the policy MUST deny. Non-empty for every provider.
    SEND_ENDPOINT_PROBES: ClassVar[tuple[tuple[str, str], ...]] = ()

    @classmethod
    @abc.abstractmethod
    def assert_allowed(cls, method: str, url: str) -> None:
        """Raise ``DraftPolicyError`` unless ``method url`` is allowlisted."""


class AuditedHttpTransport:
    """Route-allowlisted, audited, stdlib-only JSON-over-HTTP transport."""

    def __init__(
        self,
        route_policy: Any,
        *,
        provider: str = "mail",
        provider_label: str = "Mail provider",
        audit_path: str | Path | None = None,
        timeout: int = 30,
    ) -> None:
        if route_policy is None or not callable(
            getattr(route_policy, "assert_allowed", None)
        ):
            raise MailProviderError(
                "AuditedHttpTransport requires a route policy with assert_allowed()"
            )
        self.route_policy = route_policy
        self.provider = provider
        self.provider_label = provider_label
        self.timeout = timeout
        env_path = os.environ.get(AUDIT_LOG_ENV, "").strip()
        self.audit_path = Path(audit_path) if audit_path else (
            Path(env_path) if env_path else None
        )
        self.audit_log: list[dict[str, Any]] = []

    # ── audit sink (metadata only; never bodies, subjects, or queries) ───
    def _audit(self, method: str, path: str, outcome: str, started: float) -> None:
        record = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "provider": self.provider,
            "method": method.upper(),
            "path": path,
            "outcome": outcome,
            "duration_ms": round((time.monotonic() - started) * 1000, 1),
        }
        self.audit_log.append(record)
        if self.audit_path is not None:
            try:
                self.audit_path.parent.mkdir(parents=True, exist_ok=True)
                with self.audit_path.open("a", encoding="utf-8") as sink:
                    sink.write(json.dumps(record, sort_keys=True) + "\n")
            except OSError:
                pass  # auditing must never take the mail path down

    def request(
        self,
        method: str,
        url: str,
        access_token: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        started = time.monotonic()
        path = urlsplit(url).path
        try:
            self.route_policy.assert_allowed(method, url)
        except Exception:
            self._audit(method, path, "denied", started)
            raise
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
        }
        if body is not None:
            headers["Content-Type"] = "application/json"
        request = Request(url, data=body, headers=headers, method=method.upper())
        try:
            with urlopen(request, timeout=self.timeout) as response:
                raw = response.read()
        except HTTPError as exc:
            self._audit(method, path, f"http_{exc.code}", started)
            detail = exc.read().decode("utf-8", errors="replace")
            raise TransportError(
                f"{self.provider_label} returned HTTP {exc.code}: {detail[:1000]}"
            ) from exc
        except URLError as exc:
            self._audit(method, path, "connection_error", started)
            raise TransportError(
                f"{self.provider_label} connection failed: {exc.reason}"
            ) from exc
        self._audit(method, path, "ok", started)
        if not raw:
            return {}
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise TransportError(
                f"{self.provider_label} returned invalid JSON"
            ) from exc
