"""Path-level contract for the email store's stricter Git policy.

This is intentionally a small, content-blind policy: third-party names and
subjects cannot be reliably recognized after the fact, so the only safe default
is that unknown email-store artifacts are ignored.  The private overlay mirrors
these rules in ``private/.gitignore`` for an in-overlay ``data_root``.
"""
from __future__ import annotations

from pathlib import PurePosixPath

TRACKABLE = "trackable"
IGNORED = "ignored"


def email_git_disposition(path: str | PurePosixPath) -> str:
    """Return whether an email-store-relative path may enter Git history.

    Only ``index/<acct>/header.json`` and safe human annotations are trackable.
    Raw blobs/manifests, derived messages, operational state, message rows,
    triage/reverse indexes, and quoted evidence are unconditionally ignored.
    """
    parts = PurePosixPath(path).parts
    if parts and parts[0] == "email":
        parts = parts[1:]
    if not parts:
        return IGNORED
    zone = parts[0]
    if zone in {"raw", "derived", "state"}:
        return IGNORED
    if zone == "index":
        if len(parts) == 3 and parts[2] == "header.json":
            return TRACKABLE
        return IGNORED
    if zone == "annotations":
        if len(parts) >= 2 and parts[1] == "evidence":
            return IGNORED
        return TRACKABLE
    return IGNORED

