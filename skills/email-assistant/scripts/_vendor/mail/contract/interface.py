"""The send-less ``MailProvider`` contract every mail provider implements.

Two properties matter more than the method list
(design/raw-data-layer/03-provider-interfaces.md §1):

* **There is no send operation.** Not blocked — *nonexistent*. Nothing a
  consumer skill can call, misuse, or be prompt-injected into calling.
  ``MailProvider.__init_subclass__`` additionally refuses any subclass that
  defines a send-like attribute.
* **Read-only providers are first-class.** ``capabilities()`` reports
  ``drafts=False`` for a provider that cannot safely hold draft permissions
  (the Gmail default), and every consumer must handle that state.

Optional-capability operations (draft creation, delta sync, search) default to
raising :class:`CapabilityNotSupported` so a provider only exposes what its
declared capabilities actually cover.
"""
from __future__ import annotations

import abc
import re
from dataclasses import dataclass
from typing import Any, ClassVar

# Send-like attribute names are structurally refused on every provider class.
# ``(?!er)`` keeps legitimate mail vocabulary ("sender") usable.
_SEND_LIKE_RE = re.compile(r"send(?!er)", re.IGNORECASE)


class MailProviderError(RuntimeError):
    """Base failure for the mail layer (transport, provider, policy)."""


class DraftPolicyError(MailProviderError):
    """The requested operation is outside the permanent draft-only boundary."""


class CapabilityNotSupported(MailProviderError):
    """The provider does not support this optional capability."""


@dataclass(frozen=True)
class MailCapabilities:
    """What a provider can do. ``drafts=False`` providers are first-class."""

    read: bool = True
    drafts: bool = False
    delta_sync: bool = False
    search: bool = False


class MailProvider(abc.ABC):
    """Abstract mail provider: read, search, delta-sync, draft ops — never send.

    Concrete providers live in isolated folders under ``providers/`` and route
    all network I/O through the contract's audited transport
    (:mod:`mail.contract.transport`) with a provider route allowlist.
    """

    #: Stable provider identifier (folder name under ``providers/``).
    name: ClassVar[str] = "abstract"
    #: The provider's route-allowlist class (see ``transport.RoutePolicy``).
    #: Conformance requires it, with non-empty ``SEND_ENDPOINT_PROBES``.
    route_policy: ClassVar[Any] = None

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        for attr in vars(cls):
            if _SEND_LIKE_RE.search(attr):
                raise TypeError(
                    f"MailProvider subclass {cls.__name__!r} defines send-like "
                    f"attribute {attr!r}; the contract has no send operation"
                )

    # ── required (every provider) ────────────────────────────────────────
    @abc.abstractmethod
    def capabilities(self) -> MailCapabilities:
        """Report what this provider supports."""

    @abc.abstractmethod
    def verify_account(self) -> dict[str, Any]:
        """Return the authenticated account identity (for mailbox pinning)."""

    @abc.abstractmethod
    def list_inbox(self, limit: int = 10) -> list[dict[str, Any]]:
        """List recent inbox messages, newest first."""

    @abc.abstractmethod
    def list_sent(self, limit: int = 10) -> list[dict[str, Any]]:
        """List recent sent messages, newest first."""

    @abc.abstractmethod
    def list_drafts(self, limit: int = 10) -> list[dict[str, Any]]:
        """List existing drafts; every item must carry draft evidence."""

    @abc.abstractmethod
    def read_message(self, message_id: str) -> dict[str, Any]:
        """Read one message by provider message ID."""

    @abc.abstractmethod
    def review_window(self, limit: int = 20) -> dict[str, Any]:
        """Reconcile recent inbox mail against Sent and Drafts (read-only)."""

    # ── optional capabilities (fail closed by default) ───────────────────
    def delta_sync(
        self, folder: str, sync_token: str | None = None
    ) -> dict[str, Any]:
        """Incremental sync. The sync token is an OPAQUE blob the caller never
        parses; token expiry is a routine path (full resync first, delta as the
        optimization). Implemented by the email-store stage, not stage 1."""
        raise CapabilityNotSupported(f"{self.name}: delta_sync is not supported")

    def search(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        """Server-side message search. Implemented by a later stage."""
        raise CapabilityNotSupported(f"{self.name}: search is not supported")

    def create_draft(
        self,
        *,
        subject: str,
        body_text: str,
        to: list[str],
        cc: list[str] | None = None,
    ) -> dict[str, Any]:
        """Create a new unsent draft. Requires ``capabilities().drafts``; the
        returned message MUST carry provider draft evidence or the provider
        raises :class:`DraftPolicyError` (the tripwire behind the allowlist)."""
        raise CapabilityNotSupported(f"{self.name}: draft operations are not supported")

    def create_reply_draft(
        self, *, source_message_id: str, body_text: str
    ) -> dict[str, Any]:
        """Create an unsent reply draft. Same draft-evidence rule as
        :meth:`create_draft`; providers must run their duplicate-reply
        preflight (Sent/Drafts reconciliation) before any mailbox write."""
        raise CapabilityNotSupported(f"{self.name}: draft operations are not supported")
