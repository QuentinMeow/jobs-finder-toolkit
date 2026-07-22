"""Skill-local capture shim — the one place the job-search fetchers touch the store.

Wraps the vendored raw-data-layer store (``_vendor/store``) behind a tiny surface:
one lazily-built, thread-safe module-level ``CaptureSession`` for domain ``jobs``
with ``data_root`` resolved from the vendored config, plus ``set_run_context`` (the
single call ``search_jobs.py`` makes before fetching) and convenience wrappers for
each operation (``capture_board`` / ``capture_search`` / ``capture_jd`` /
``capture_scrape`` + a ``group`` helper for the bespoke multi-request flows).

Hard rules (mirroring the store's own capture contract, enforced again here so a
fetcher can never be harmed):

* **Never raises into the fetcher.** Every entry point is totality-wrapped: any
  internal error — including a failed profile-slug allocation — becomes one stderr
  warning and returns ``None``; the fetch continues.
* **Never locks the fetch path.** Session construction takes a lock; capturing does
  not (the store writes unique fetch dirs with content-addressed blobs).
* **Store disabled ⇒ silent no-op.** When ``data_root`` is unset the session is
  disabled and every wrapper returns ``None`` (capture emits one info line, once).
* **Neutral context only.** ``company`` is the registry name mechanically slugified
  to ``[a-z0-9-]``; ``profile`` is the allocated ``profile-NN`` slug. Nothing else —
  the manifest layer hard-rejects unknown context keys, which is the safety net.
  A profile-slug allocation failure captures WITHOUT the profile key (never drops
  the capture).
"""
from __future__ import annotations

import json
import re
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

# Self-contained skill: put this skill's scripts/ (so ``_vendor`` is an importable
# package) and _vendor/ (so ``import config`` finds the vendored loader) on the path.
_SKILL_SCRIPTS = Path(__file__).resolve().parent
for _p in (str(_SKILL_SCRIPTS), str(_SKILL_SCRIPTS / "_vendor")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

_TOOL_VERSION = "store-capture/1 job-search"

# Reentrant so the profile-allocation path can call _get_session() while holding it.
_LOCK = threading.RLock()
_SESSION = None
_SESSION_BUILT = False
_PROFILE_LABEL: str | None = None
_PROFILE_SLUG: str | None = None
_PROFILE_ALLOC_ATTEMPTED = False
_WARNED: set[str] = set()

_SLUG_STRIP_RE = re.compile(r"[^a-z0-9]+")


def _warn_once(key: str, msg: str) -> None:
    with _LOCK:
        if key in _WARNED:
            return
        _WARNED.add(key)
    print(f"capture: WARNING {msg}", file=sys.stderr)


def slugify_company(name: str | None) -> str:
    """Mechanically map a registry name to a neutral ``[a-z0-9-]`` slug (or '')."""
    if not name:
        return ""
    return _SLUG_STRIP_RE.sub("-", str(name).lower()).strip("-")


def set_run_context(profile_label: str | None) -> None:
    """Record the active profile label (its slug is allocated lazily on first capture)."""
    global _PROFILE_LABEL
    _PROFILE_LABEL = (profile_label or "").strip() or None


def _get_session():
    """Return the lazily-built (thread-safe) CaptureSession, or None if disabled."""
    global _SESSION, _SESSION_BUILT
    if _SESSION_BUILT:
        return _SESSION
    with _LOCK:
        if _SESSION_BUILT:
            return _SESSION
        try:
            import config  # vendored toolkit config loader
            from _vendor.store.capture import CaptureSession
            _SESSION = CaptureSession("jobs", config.data_root(),
                                      tool_version=_TOOL_VERSION)
        except Exception as exc:  # noqa: BLE001 — never break a fetch
            _warn_once("session", f"store capture unavailable: {exc}")
            _SESSION = None
        _SESSION_BUILT = True
    return _SESSION


def _profile_slug() -> str | None:
    """The allocated ``profile-NN`` slug for the run, or None (allocate once, lazily)."""
    global _PROFILE_SLUG, _PROFILE_ALLOC_ATTEMPTED
    if _PROFILE_SLUG is not None or _PROFILE_ALLOC_ATTEMPTED:
        return _PROFILE_SLUG
    if not _PROFILE_LABEL:
        return None
    with _LOCK:
        if _PROFILE_SLUG is not None or _PROFILE_ALLOC_ATTEMPTED:
            return _PROFILE_SLUG
        _PROFILE_ALLOC_ATTEMPTED = True
        session = _get_session()
        if session is None or getattr(session, "layout", None) is None:
            return None
        try:
            from _vendor.store.identifiers import IdentifierRegistry
            reg = IdentifierRegistry(session.layout.identifiers)
            _PROFILE_SLUG = reg.allocate("profile", _PROFILE_LABEL)
        except Exception as exc:  # noqa: BLE001 — capture WITHOUT profile, never drop
            _warn_once("profile-alloc",
                       f"profile-slug allocation failed; capturing without a "
                       f"profile context key: {exc}")
            _PROFILE_SLUG = None
    return _PROFILE_SLUG


def _context(company: str | None) -> dict | None:
    ctx: dict = {}
    slug = slugify_company(company)
    if slug:
        ctx["company"] = slug
    prof = _profile_slug()
    if prof:
        ctx["profile"] = prof
    return ctx or None


class _BytesResp:
    """A duck-typed HTTP result for captures that have no urllib exchange (JobSpy)."""

    def __init__(self, status: int, body: bytes, *, content_type: str | None = None,
                 headers: dict | None = None, duration_ms: int | None = None,
                 ok: bool | None = None, error: str | None = None) -> None:
        self.status = int(status or 0)
        self.body = body or b""
        self.content_type = content_type
        self.headers = headers or {}
        self.duration_ms = duration_ms
        self.ok = ok if ok is not None else (200 <= self.status < 300)
        self.error = error


def make_resp(status, body, *, content_type=None, headers=None, duration_ms=None,
              ok=None, error=None) -> _BytesResp:
    """Build a duck-typed HTTP result from raw bytes (for bespoke opener flows)."""
    return _BytesResp(status, body, content_type=content_type, headers=headers,
                      duration_ms=duration_ms, ok=ok, error=error)


# Response-header names whose VALUES may carry a credential/session secret. We keep
# the header NAME (preserving the over-capture signal that it was present) but
# replace the value with a redaction marker. Matched as a lowercase substring so
# Set-Cookie / x-apple-csrf-token / X-RapidAPI-Key / WWW-Authenticate / Authorization
# / X-Signature are all covered without an exhaustive list.
_SENSITIVE_HEADER_SUBSTRINGS = ("cookie", "auth", "token", "secret", "signature", "key")
_REDACTED = "[redacted]"


def _redact_headers(headers):
    """Return a copy of response headers with credential-bearing VALUES redacted."""
    if not headers:
        return headers
    out = {}
    for name, value in headers.items():
        low = str(name).lower()
        out[name] = _REDACTED if any(s in low for s in _SENSITIVE_HEADER_SUBSTRINGS) \
            else value
    return out


def safe_item_count(body: bytes | None, key: str | None = None) -> int | None:
    """Best-effort item count from a JSON body — never raises (over-capture only).

    Deliberately independent of the fetcher's real parse: it returns None on any
    problem so it can run BEFORE capture without ever blocking capture-of-raw.
    """
    if not body:
        return None
    try:
        data = json.loads(body.decode("utf-8", "replace"))
    except Exception:  # noqa: BLE001
        return None
    if key is not None:
        value = data.get(key) if isinstance(data, dict) else None
        return len(value) if isinstance(value, (list, dict)) else None
    return len(data) if isinstance(data, (list, dict)) else None


def _capture(operation: str, source: str, url: str, resp, *, company=None,
             item_count=None, query=None, pagination=None, params=None, group=None):
    """Core capture. Totality-wrapped; returns the fetch id or None."""
    target = group if group is not None else _get_session()
    if target is None:
        return None
    try:
        request: dict = {"url": url}
        if params:
            request["params"] = params
        return target.capture_fetch(
            source=source,
            operation=operation,
            request=request,
            status=getattr(resp, "status", 0) or 0,
            payload_bytes=(resp.body if getattr(resp, "body", None) else None),
            content_type=getattr(resp, "content_type", None),
            response_headers=_redact_headers(getattr(resp, "headers", None)),
            item_count=item_count,
            query=query,
            pagination=pagination,
            duration_ms=getattr(resp, "duration_ms", None),
            context=_context(company),
            error=(None if getattr(resp, "ok", True) else getattr(resp, "error", None)),
        )
    except Exception as exc:  # noqa: BLE001 — never break a fetch
        _warn_once(f"cap:{source}:{operation}", f"capture failed ({source}): {exc}")
        return None


# ── operation wrappers ───────────────────────────────────────
def capture_board(company, url, resp, *, source, item_count=None, query=None,
                  params=None, group=None):
    """Capture a complete board dump (greenhouse/ashby/lever)."""
    return _capture("board", source, url, resp, company=company,
                    item_count=item_count, query=query, params=params, group=group)


def capture_search(company, url, resp, *, source, item_count=None, query=None,
                   pagination=None, params=None, group=None):
    """Capture a keyword/capped/truncated sample (workday/amazon/apple/meta/SR)."""
    return _capture("search", source, url, resp, company=company,
                    item_count=item_count, query=query, pagination=pagination,
                    params=params, group=group)


def capture_jd(url, resp, *, source="web", company=None, group=None):
    """Capture a job-description page fetch."""
    return _capture("jd", source, url, resp, company=company, group=group)


def capture_scrape(source, url, resp, *, company=None, item_count=None, query=None,
                   params=None, group=None):
    """Capture already-normalized aggregator output (opinion-grade evidence)."""
    return _capture("scrape", source, url, resp, company=company,
                    item_count=item_count, query=query, params=params, group=group)


def capture_scrape_bytes(source, url, body: bytes, *, content_type="application/json",
                         status=200, company=None, item_count=None, query=None,
                         params=None):
    """Capture a scrape that has no HTTP exchange (JobSpy: serialized rows)."""
    return capture_scrape(source, url, make_resp(status, body,
                                                 content_type=content_type),
                          company=company, item_count=item_count, query=query,
                          params=params)


# ── group helper ─────────────────────────────────────────────
class _NullGroup:
    """A no-op group used when the store is disabled, so bespoke flows read uniformly."""

    def capture_fetch(self, **_kwargs):
        return None

    def attest(self, complete: bool) -> None:  # noqa: D401
        return None

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return False


def _group_id(kind: str, company: str | None) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}-{kind}-{slugify_company(company) or 'x'}"


def group(kind: str, company: str | None, *, expected: int | None = None):
    """Open a fetch group (context manager). Never raises; a disabled store gives a no-op.

    Members are captured by passing ``group=<handle>`` to the operation wrappers;
    the handle writes a group attestation manifest on exit.
    """
    session = _get_session()
    if session is None:
        return _NullGroup()
    try:
        return session.group(_group_id(kind, company), expected=expected)
    except Exception as exc:  # noqa: BLE001
        _warn_once("group", f"group open failed: {exc}")
        return _NullGroup()


def _reset_for_tests() -> None:
    """Reset module state (test-only; a new run/process rebuilds lazily)."""
    global _SESSION, _SESSION_BUILT, _PROFILE_LABEL, _PROFILE_SLUG
    global _PROFILE_ALLOC_ATTEMPTED
    with _LOCK:
        _SESSION = None
        _SESSION_BUILT = False
        _PROFILE_LABEL = None
        _PROFILE_SLUG = None
        _PROFILE_ALLOC_ATTEMPTED = False
        _WARNED.clear()
