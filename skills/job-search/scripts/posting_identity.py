"""Posting identity (Stage 2) — platform-unique keys, versioned URL canonicalizer.

A posting's key must survive the things that happen over a months-long hunt: board
renames, registry edits, ATS migrations. So we key on the most stable identifier
available, in order (design 02 §3):

1. **Platform-unique ATS id, no board token** — ``gh-<id>`` / ``lever-<uuid>`` /
   ``ashby-<uuid>`` / ``sr-<id>``. These ids are unique across the whole platform,
   so a company renaming its board slug cannot fork identity.
2. **Workday requisition, namespaced by the registry's canonical company** —
   ``wd-<company-slug>-<req>`` (req is unique only *per company*).
3. **Canonicalized-URL key** — ``url-<12-hex>`` for aggregator rows that carry a
   stable embedded id (LinkedIn/Indeed/jobicy/remoteok/themuse).
4. **Content key** (last resort) — ``ck-<hash>`` over company + normalized title +
   the SORTED location set (sorted because some sources return locations in
   unstable order). Content-keyed entities are marked ``identity: weak``.

The URL canonicalizer is a **written, versioned spec** (see ``CANONICALIZER_VERSION``
and ``canonicalize_url``): a version bump is treated like a schema change (bump →
full rebuild → the url-hash keys change → unpinned entities re-key freely; pinned
entities never silently move — the key registry gates that).
"""
from __future__ import annotations

import hashlib
import re
import urllib.parse

# ── versioned URL canonicalizer ──────────────────────────────
# CANONICALIZER_VERSION bump == schema-change treatment. The rules, frozen at this
# version:
#   1. scheme + host lowercased; a missing scheme is treated as https.
#   2. tracking / attribution query params stripped: utm_* , gh_src, lever-origin,
#      ref, source (case-insensitive); every other query param is KEPT (sorted).
#   3. the URL fragment (#...) is dropped.
#   4. trailing-slash normalized off the path (except the bare "/" root).
# A change to ANY of these rules is a CANONICALIZER_VERSION bump.
CANONICALIZER_VERSION = 1

_TRACKING_PARAM_RE = re.compile(r"^(utm_.*|gh_src|lever-origin|ref|source)$", re.I)


def canonicalize_url(url: str) -> str:
    """Return the canonical form of ``url`` per the frozen v1 rules above."""
    raw = (url or "").strip()
    if not raw:
        return ""
    if "://" not in raw:
        raw = "https://" + raw
    parts = urllib.parse.urlsplit(raw)
    scheme = (parts.scheme or "https").lower()
    host = (parts.hostname or "").lower()
    if parts.port:
        host = f"{host}:{parts.port}"
    path = parts.path or ""
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")
    kept = [(k, v) for k, v in urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
            if not _TRACKING_PARAM_RE.match(k)]
    kept.sort()
    query = urllib.parse.urlencode(kept)
    return urllib.parse.urlunsplit((scheme, host, path, query, ""))


def _sha12(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def url_key(url: str) -> str | None:
    """``url-<12-hex sha256 prefix>`` over the canonicalized URL, or ``None``."""
    canon = canonicalize_url(url)
    return f"url-{_sha12(canon)}" if canon else None


# ── content key (weak identity, last resort) ─────────────────
_TITLE_WS_RE = re.compile(r"\s+")


def _norm_title(title: str) -> str:
    return _TITLE_WS_RE.sub(" ", (title or "").strip().lower())


def _norm_company(company: str) -> str:
    return _TITLE_WS_RE.sub(" ", (company or "").strip().lower())


def content_key(company: str, title: str, locations) -> str:
    """``ck-<hash>`` over company + normalized title + the SORTED location set.

    Locations are sorted so a source returning them in unstable order does not
    fabricate a new identity. Marked ``identity: weak`` by the builder.
    """
    locs = sorted({str(x).strip().lower() for x in (locations or []) if str(x).strip()})
    basis = "\x1f".join([_norm_company(company), _norm_title(title), "|".join(locs)])
    return f"ck-{_sha12(basis)}"


# ── platform id keys ─────────────────────────────────────────
_SLUG_STRIP_RE = re.compile(r"[^a-z0-9]+")


def _slug(value: str) -> str:
    return _SLUG_STRIP_RE.sub("-", str(value or "").lower()).strip("-")


def gh_key(native_id: str) -> str:
    return f"gh-{_slug(native_id)}"


def ashby_key(native_id: str) -> str:
    return f"ashby-{_slug(native_id)}"


def lever_key(native_id: str) -> str:
    return f"lever-{_slug(native_id)}"


def sr_key(native_id: str) -> str:
    return f"sr-{_slug(native_id)}"


def amazon_key(native_id: str) -> str:
    return f"amazon-{_slug(native_id)}"


def apple_key(native_id: str) -> str:
    return f"apple-{_slug(native_id)}"


def meta_key(native_id: str) -> str:
    return f"meta-{_slug(native_id)}"


def workday_key(company_slug: str, req: str) -> str:
    return f"wd-{_slug(company_slug)}-{_slug(req)}"


# Strength markers stored in the index / entity.
STRONG = "strong"
WEAK = "weak"

# Platform-unique IDs (stable across board renames). Big-tech search sources
# (amazon/apple/meta) carry stable per-platform posting IDs in the payload, so we
# key on those rather than their slug-embedding URLs (which fork when a title slug
# changes). Workday is the exception: its req is unique only per company, so it is
# namespaced by the registry canonical (see identify()).
_PLATFORM_KEYERS = {
    "greenhouse": gh_key,
    "ashby": ashby_key,
    "lever": lever_key,
    "smartrecruiters": sr_key,
    "amazon": amazon_key,
    "apple": apple_key,
    "meta": meta_key,
}


def identify(row: dict, *, company_slug: str) -> tuple[str, str]:
    """Return ``(entity_key, strength)`` for a parsed row.

    ``company_slug`` is the registry-canonical company slug (used only for Workday
    namespacing and as the content-key company component). Strength is ``strong``
    for platform-id / workday-req / url keys and ``weak`` for content keys.
    """
    source = row.get("source")
    native = row.get("native_id")

    keyer = _PLATFORM_KEYERS.get(source)
    if keyer is not None and native:
        return keyer(native), STRONG

    if source == "workday" and native:
        return workday_key(company_slug or "unknown", native), STRONG

    # Aggregator / scrape rows: a stable URL is the preferred identity.
    uk = url_key(row.get("url", ""))
    if uk is not None:
        return uk, STRONG

    # Last resort: a weak content key (company + title + sorted locations).
    company = company_slug or row.get("company_name") or ""
    locs = [row.get("location", "")]
    return content_key(company, row.get("title", ""), locs), WEAK
