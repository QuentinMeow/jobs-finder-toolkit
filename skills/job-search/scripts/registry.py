"""Canonical company registry + resolver for the job-search skill.

Single source of truth for company IDENTITY, poll config, and the blacklist:
`companies.yaml` (this skill dir). Both the fetch pipeline and the skip/blacklist
matching resolve raw company strings (from boards AND aggregators) through this
module so that name drift (e.g. registry "Arize" / token "arizeai" vs an
aggregator's "Arize AI") no longer breaks matching.

Entry shapes in companies.yaml:
  - POLLED       : name, ats, token, [host, site, search_terms], tags, [aliases],
                   [poll_batch]
  - IDENTITY-ONLY: name, [aliases], blacklist    (no ats/token -> never polled)

Match keys for an entry = normalized {name} + {aliases} + {token}. `canonical`
maps any raw string to the entry's display `name`; unknown strings resolve to
None and callers fall back to the raw normalized string (so aggregator-only
companies keep working exactly as before).

Stdlib + PyYAML only (runs on the repo venv without extra installs).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

SKILL_DIR = Path(__file__).resolve().parents[1]
REGISTRY_PATH = SKILL_DIR / "companies.yaml"

_WS_RE = re.compile(r"\s+")
_BATCH_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
_SLUGIFY_RE = re.compile(r"[^a-z0-9]+")

# Trailing legal / company-style suffix tokens. Two names that differ ONLY by a
# run of these trailing tokens (plus surrounding punctuation / a trailing
# possessive) name the same employer for identity purposes — e.g. "Acme" ==
# "Acme Ltd." == "Acme Corp, Inc.". Kept deliberately conservative (no broad
# fuzzy matching): tokens like "ai", "labs", "systems" carry real disambiguating
# meaning (Arize vs Arize AI) and are NOT stripped.
_LEGAL_SUFFIXES = {
    "ltd", "limited", "inc", "incorporated", "corp", "corporation",
    "co", "company", "llc", "llp", "lp", "plc", "gmbh",
    "technologies", "technology",
}
# Characters trimmed from the edges of a token before the suffix comparison, so
# "corp," / "inc." / a bare "acme," all reduce cleanly.
_PUNCT = ".,"
# Namespace sentinel for a suffix-stripped "comparable" key. Keeping comparable
# keys in their own key-space (a real company name can never contain this
# control char) means a comparable form only ever matches another comparable
# form, never a raw/exact key that coincidentally equals the stripped base.
_CMP_PREFIX = "\x00cmp\x00"


def _slugify(value: str | None) -> str:
    """Mechanically map a name to a neutral ``[a-z0-9-]`` slug (store context form)."""
    return _SLUGIFY_RE.sub("-", str(value or "").lower()).strip("-")

SUPPORTED_ATS = {
    "greenhouse", "ashby", "lever", "smartrecruiters", "workday",
    "amazon", "apple", "meta",
}


def normalize(name: str | None) -> str:
    """Lowercase, strip, collapse internal whitespace (matches log/blacklist keys)."""
    if not name:
        return ""
    return _WS_RE.sub(" ", str(name).strip().lower())


def comparable_base(name: str | None) -> str:
    """Normalized name with trailing legal suffixes / possessive / edge-punctuation removed.

    Strips ONLY from the trailing edge and never the last remaining token, so:
      - "Acme Ltd."          -> "acme"       (suffix stripped)
      - "Acme Corp, Inc."    -> "acme"       (repeated + punctuation)
      - "McDonald's Co"      -> "mcdonald"   (suffix then possessive)
      - "Inc Magazine"       -> "inc magazine" (a suffix word that is NOT trailing
                                                is left intact)
      - "Co" / "LLC"         -> "co" / "llc" (a name that is only a suffix word is
                                              never emptied — short-legal-name guard)

    Because it operates on whole whitespace tokens, an embedded look-alike
    ("Coinbase", "Costar", "Incubator") is never mistaken for a suffix.
    """
    tokens = normalize(name).split()
    changed = True
    while tokens and changed:
        changed = False
        last = tokens[-1].strip(_PUNCT)
        if last.endswith("'s") and len(last) > 2:      # trailing possessive
            tokens[-1] = last[:-2]
            changed = True
            continue
        if len(tokens) > 1 and last in _LEGAL_SUFFIXES:  # trailing legal suffix
            tokens.pop()
            changed = True
    return " ".join(t.strip(_PUNCT) for t in tokens if t.strip(_PUNCT)).strip()


def lint_entries(entries: list[dict]) -> list[str]:
    """Return deterministic offline schema/identity errors for registry rows."""
    errors: list[str] = []
    key_owner: dict[str, str] = {}
    for index, entry in enumerate(entries):
        label = f"companies[{index}]"
        if not isinstance(entry, dict):
            errors.append(f"{label}: entry must be a mapping")
            continue

        name = str(entry.get("name") or "").strip()
        if not name:
            errors.append(f"{label}: name is required")
            name = label
        ats = str(entry.get("ats") or "").strip().lower()
        token = str(entry.get("token") or "").strip()

        if ats:
            if ats not in SUPPORTED_ATS:
                errors.append(f"{name}: unsupported ats {ats!r}")
            if not token:
                errors.append(f"{name}: token is required for a polled entry")
            tags = entry.get("tags")
            if not isinstance(tags, list) or not any(str(t).strip() for t in tags):
                errors.append(f"{name}: non-empty tags list is required")
            if ats == "workday":
                for field in ("host", "site"):
                    if not str(entry.get(field) or "").strip():
                        errors.append(f"{name}: {field} is required for workday")
        else:
            if token:
                errors.append(f"{name}: token requires ats")
            if not entry.get("blacklist"):
                errors.append(
                    f"{name}: identity-only rows must carry a blacklist reason")

        aliases = entry.get("aliases") or []
        if not isinstance(aliases, list):
            errors.append(f"{name}: aliases must be a list")
            aliases = []

        # Optional ATS-migration records: `previous: [{ats, token, until}]`. A
        # declared record LICENSES continuation matching across that one boundary
        # (store builder); without a record no cross-ATS merge ever happens.
        previous = entry.get("previous")
        if previous is not None:
            if not isinstance(previous, list):
                errors.append(f"{name}: previous must be a list of migration records")
            else:
                for rec in previous:
                    if not isinstance(rec, dict):
                        errors.append(f"{name}: each previous record must be a mapping")
                        continue
                    prev_ats = str(rec.get("ats") or "").strip().lower()
                    if prev_ats not in SUPPORTED_ATS:
                        errors.append(
                            f"{name}: previous.ats {rec.get('ats')!r} unsupported")
                    if not str(rec.get("token") or "").strip():
                        errors.append(f"{name}: previous.token is required")
        batch = entry.get("poll_batch")
        if batch is not None and (
                not isinstance(batch, str) or not _BATCH_RE.fullmatch(batch.strip())):
            errors.append(
                f"{name}: poll_batch must match {_BATCH_RE.pattern!r}")

        raw_keys = [name, *aliases]
        if token:
            raw_keys.append(token)
        for raw in raw_keys:
            key = normalize(raw)
            if not key:
                errors.append(f"{name}: empty identity key")
                continue
            owner = key_owner.get(key)
            if owner is not None and owner != name:
                errors.append(
                    f"{name}: identity key {key!r} collides with {owner!r}")
            else:
                key_owner[key] = name
    return errors


class Registry:
    """Loaded company registry with canonical-name + blacklist resolution."""

    def __init__(self, entries: list[dict]):
        self.entries: list[dict] = [e for e in entries if isinstance(e, dict)]
        self._key_to_canonical: dict[str, str] = {}
        self._canonical_to_keys: dict[str, set[str]] = {}
        self._blacklist: dict[str, str] = {}   # canonical name -> reason
        self._slug_to_canonical: dict[str, str] = {}   # slugified key -> canonical
        # Suffix-stripped fallbacks. `_comparable_to_canonical` resolves a raw
        # variant to its canonical name ONLY when the stripped base is
        # unambiguous; `_ambiguous_bases` are bases shared by >1 distinct
        # registered company, for which we refuse to emit/resolve a comparable
        # key at all (never conflate two known-distinct employers).
        self._comparable_to_canonical: dict[str, str] = {}
        self._ambiguous_bases: set[str] = set()
        self._build_index()

    def _entry_keys(self, entry: dict) -> set[str]:
        keys = {normalize(entry.get("name"))}
        for a in (entry.get("aliases") or []):
            keys.add(normalize(a))
        if entry.get("token"):
            keys.add(normalize(entry.get("token")))
        keys.discard("")
        return keys

    def _build_index(self) -> None:
        for entry in self.entries:
            canonical = (entry.get("name") or "").strip()
            if not canonical:
                continue
            keys = self._entry_keys(entry)
            self._canonical_to_keys.setdefault(canonical, set()).update(keys)
            for key in keys:
                existing = self._key_to_canonical.get(key)
                if existing and existing != canonical:
                    # Non-fatal: surface the collision so it can be fixed by hand
                    # instead of silently attaching a string to the wrong company.
                    print(f"[registry] WARNING: match key {key!r} maps to both "
                          f"{existing!r} and {canonical!r}; keeping {existing!r}.",
                          file=sys.stderr)
                    continue
                self._key_to_canonical[key] = canonical
                # A store-neutral slug of every match key resolves the manifest's
                # `context.company` slug back to the registry canonical name.
                slug = _slugify(key)
                if slug:
                    self._slug_to_canonical.setdefault(slug, canonical)
            if entry.get("blacklist"):
                reason = entry["blacklist"]
                self._blacklist[canonical] = reason if isinstance(reason, str) else ""

        # Build the comparable-base -> canonical fallback from the exact keys we
        # just indexed. A base owned by two distinct canonicals is ambiguous and
        # is dropped (canonical() abstains; no comparable key is emitted for it).
        base_owners: dict[str, set[str]] = {}
        for key, canonical in self._key_to_canonical.items():
            base = comparable_base(key)
            if base:
                base_owners.setdefault(base, set()).add(canonical)
        for base, owners in base_owners.items():
            if len(owners) == 1:
                self._comparable_to_canonical[base] = next(iter(owners))
            else:
                self._ambiguous_bases.add(base)

    def _augment_with_comparable(self, keys: set[str]) -> set[str]:
        """Add the namespaced comparable form of each key (skipping ambiguous bases)."""
        out = set(keys)
        for key in keys:
            base = comparable_base(key)
            if base and base not in self._ambiguous_bases:
                out.add(_CMP_PREFIX + base)
        out.discard("")
        return out

    # ---- resolution -------------------------------------------------------- #
    def canonical(self, raw: str | None) -> str | None:
        """Map a raw company string to its canonical display name, else None.

        Exact normalized lookup first; then an unambiguous suffix-stripped
        fallback, so an aggregator variant ("Acme Ltd.") resolves to the
        registered short name ("Acme"). Abstains (None) when the stripped base is
        shared by more than one registered company.
        """
        hit = self._key_to_canonical.get(normalize(raw))
        if hit is not None:
            return hit
        base = comparable_base(raw)
        if base and base not in self._ambiguous_bases:
            return self._comparable_to_canonical.get(base)
        return None

    def match_keys(self, raw: str | None) -> set[str]:
        """All match keys for the company `raw` resolves to.

        Each set carries the exact normalized keys PLUS a namespaced comparable
        form per key, so two spellings of one employer that differ only by a
        trailing legal suffix ("Acme" vs "Acme Ltd.") intersect. Falls back to
        the raw string (+ its comparable form) when unknown, so aggregator-only
        companies absent from the registry still match across suffix variants.
        """
        canonical = self.canonical(raw)
        keys = (set(self._canonical_to_keys.get(canonical, set()))
                if canonical is not None else set())
        norm = normalize(raw)
        if norm:
            keys.add(norm)
        return self._augment_with_comparable(keys)

    def canonical_for_slug(self, slug: str | None) -> str | None:
        """Reverse a store ``context.company`` slug to the registry canonical name.

        The store captures ``context.company`` as ``slugify(registry_name)``; this
        maps it back so the builder can namespace Workday keys and label entities
        with the stable canonical company. Unknown slugs resolve to ``None``.
        """
        if not slug:
            return None
        return self._slug_to_canonical.get(str(slug).strip().lower())

    def migration_records(self, raw: str | None) -> list[dict]:
        """Declared ATS-migration records for a company (``previous:`` list).

        Each record ``{ats, token, until}`` LICENSES the store builder to continue a
        posting's identity across that one ATS boundary (same company + normalized
        title + JD content hash). No record → the builder never merges across ATSes.
        """
        canonical = self.canonical(raw) or (raw or "")
        for entry in self.entries:
            if (entry.get("name") or "").strip() == canonical:
                prev = entry.get("previous") or []
                return [r for r in prev if isinstance(r, dict)]
        return []

    def is_blacklisted(self, raw: str | None) -> tuple[bool, str | None]:
        """(True, reason) if `raw` resolves to a blacklisted company, else (False, None)."""
        canonical = self.canonical(raw)
        if canonical is not None and canonical in self._blacklist:
            return True, self._blacklist[canonical] or None
        return False, None

    def blacklisted_keys(self) -> set[str]:
        """Every match key belonging to a blacklisted company (incl. comparable forms)."""
        keys: set[str] = set()
        for canonical in self._blacklist:
            keys |= self._canonical_to_keys.get(canonical, set())
        return self._augment_with_comparable(keys)

    # ---- tag lookups ------------------------------------------------------- #
    def tagged_keys(self, tags: list[str] | None) -> set[str]:
        """Union of match keys for every entry carrying any of `tags`.

        Used to flag postings whose company is a known AI-native / AI-infra
        employer (e.g. tagged ``ai-lab`` / ``ai-infra`` / ``ai-native``), so the
        scorer can boost "Kubernetes infra role AT an AI-native company" even for
        aggregator hits whose company happens to be in the registry.
        """
        tagset = {str(t).strip().lower() for t in (tags or []) if str(t).strip()}
        if not tagset:
            return set()
        keys: set[str] = set()
        for entry in self.entries:
            etags = {str(t).lower() for t in (entry.get("tags") or [])}
            if tagset & etags:
                keys |= self._entry_keys(entry)
        keys.discard("")
        return self._augment_with_comparable(keys)

    # ---- polling ----------------------------------------------------------- #
    def poll_companies(
        self,
        tags: list[str] | None = None,
        batches: list[str] | None = None,
    ) -> list[dict]:
        """Return pollable entries selected by domain tags and explicit batches.

        Rows carrying ``poll_batch`` are opt-in so a large research expansion never
        turns an ordinary profile run into a thousand-board crawl. Supplying batches
        selects only those batches; omitting them keeps only unbatched legacy rows.
        """
        pollable = [e for e in self.entries if e.get("ats")]
        if batches:
            batchset = {str(b).strip().lower() for b in batches if str(b).strip()}
            pollable = [
                e for e in pollable
                if str(e.get("poll_batch") or "").strip().lower() in batchset
            ]
        else:
            pollable = [e for e in pollable if not e.get("poll_batch")]
        if tags:
            tagset = {str(t).strip().lower() for t in tags if str(t).strip()}
            pollable = [
                c for c in pollable
                if tagset & {str(t).lower() for t in (c.get("tags") or [])}
            ]
        return pollable


def _overlay_blacklist_paths() -> list[Path]:
    """Candidate locations of the optional git-ignored overlay blacklist.

    Personal data mounts at the git-ignored ``private/`` overlay at the repo root.
    We anchor on the active config file's directory when the vendored config loader
    is importable, and also try the repo root relative to this skill. The overlay is
    never required — it simply keeps personal skip rules (e.g. the candidate's own
    employer, or companies that don't sponsor) OUT of the public registry.
    """
    bases: list[Path] = []
    try:
        from _vendor import config as _cfg  # type: ignore
        bases.append(_cfg.config_path().parent)
    except Exception:
        pass
    bases.append(SKILL_DIR.parents[1])  # skills/job-search -> repo root

    out: list[Path] = []
    seen: set[Path] = set()
    for base in bases:
        p = (base / "private" / "job-search" / "blacklist.yaml").resolve()
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out


def load_registry(path: str | Path | None = None) -> Registry:
    """Load the canonical company registry from companies.yaml.

    When loading the DEFAULT registry (``path is None``), also merges an optional
    git-ignored overlay blacklist (``private/job-search/blacklist.yaml``) if
    present. Overlay rows use the same entry shape as identity-only blacklist rows
    (``name`` + optional ``aliases`` + ``blacklist`` reason), so personal skip
    rules never live in the public ``companies.yaml``.
    """
    p = Path(path) if path else REGISTRY_PATH
    data = yaml.safe_load(p.read_text()) if p.exists() else {}
    entries = list((data or {}).get("companies") or [])
    if path is None:
        for overlay in _overlay_blacklist_paths():
            if overlay.exists():
                odata = yaml.safe_load(overlay.read_text()) or {}
                entries.extend(odata.get("companies") or [])
                break
    return Registry(entries)
