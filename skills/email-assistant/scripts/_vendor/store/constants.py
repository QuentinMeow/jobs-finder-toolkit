"""Pinned constants and regexes for the store library — single source of truth.

Every tunable number the store cares about lives here so a reviewer can find and
change it in one place. Nothing here depends on anything outside the stdlib.
"""
from __future__ import annotations

import re

# zstd compression level for payload blobs. A blob's identity is the sha256 of its
# UNCOMPRESSED bytes, so this level is a pure storage detail: changing it (or the
# zstd library version) re-compresses to different file bytes but the SAME blob
# name, and a re-written blob dedupes to a no-op.
ZSTD_LEVEL = 10

# Manifest envelope schema version. Additive-only and forever (manifests are the
# observation log); a genuine break would need ENVELOPE_SCHEMA = 2 plus a reader
# that handles both — never a silent bump.
ENVELOPE_SCHEMA = 1

# Soft size ceiling for the tracked example fixture store (examples/data/).
# Exceeding it prints a loud human-facing WARNING and exits 0 — never a silent
# grow, never a hard block. A deliberate, visible ``<data_root>/FIXTURE_SIZE_LIMIT_KB``
# file may raise it (the sanctioned human-approved path).
FIXTURE_SIZE_SOFT_LIMIT_BYTES = 100 * 1024
FIXTURE_SIZE_OVERRIDE_FILENAME = "FIXTURE_SIZE_LIMIT_KB"

# A builder lock is considered stale (and stealable) after this many seconds. A
# skipped incremental build costs nothing — the ledger catches it up next run.
LOCK_STALE_SECONDS = 300

# Path-slug rule: lowercase letters, digits, hyphens only. Enforced on every
# raw/derived path component, with case-collision detection, because the real
# store lives on a case-insensitive Mac filesystem while CI runs on Linux — a
# mixed-case key would collide on one platform and not the other.
SLUG_RE = re.compile(r"^[a-z0-9-]+$")
SLUG_RULE = "path components must match [a-z0-9-] (lowercase slug)"

# Neutral owner-identifier rule. Agents can NEVER hand-type one of these; the
# library allocates and resolves them (identifiers.py). Every identifier slug
# field is validated against this at write time and a non-match is a hard error
# naming this rule — so a real name/email physically cannot land in a manifest.
IDENTIFIER_RE = re.compile(r"^(profile|acct)-[0-9]{2}$")
IDENTIFIER_RULE = "owner-identifier slugs must match (profile|acct)-[0-9]{2}"

# Manifest context keys whose values are neutral owner-identifiers (validated
# against IDENTIFIER_RE) vs. neutral registry slugs (validated against SLUG_RE).
IDENTIFIER_CONTEXT_KEYS = ("profile", "account", "mailbox")
SLUG_CONTEXT_KEYS = ("company",)

# Fetch-id shape: <UTC compact timestamp>-<6-digit per-run seq>-<hex suffix>.
# The suffix makes fetch directories unique across concurrent processes with no
# lock; the seq orders captures within one run.
FETCH_ID_RE = re.compile(r"^[0-9]{8}T[0-9]{6}Z-[0-9]{6}-[0-9a-f]{6}$")

# The typed fetch operations. ``board`` is reserved for truly complete board
# dumps (attested via the group mechanism); ``search`` is a keyword/capped sample
# where absence means nothing; ``jd`` is a posting-page fetch; ``scrape`` is
# already-normalized aggregator output; ``group`` is a group attestation manifest.
FETCH_OPERATIONS = ("board", "search", "jd", "scrape", "group")

# The five zones of a domain root.
ZONES = ("raw", "derived", "index", "annotations", "state")
