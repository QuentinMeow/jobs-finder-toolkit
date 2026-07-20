"""Canonical company registry + resolver for the job-search skill.

Single source of truth for company IDENTITY, poll config, and the blacklist:
`companies.yaml` (this skill dir). Both the fetch pipeline and the skip/blacklist
matching resolve raw company strings (from boards AND aggregators) through this
module so that name drift (e.g. registry "Arize" / token "arizeai" vs an
aggregator's "Arize AI") no longer breaks matching.

Entry shapes in companies.yaml:
  - POLLED       : name, ats, token, [host, site, search_terms], tags, [aliases]
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


def normalize(name: str | None) -> str:
    """Lowercase, strip, collapse internal whitespace (matches log/blacklist keys)."""
    if not name:
        return ""
    return _WS_RE.sub(" ", str(name).strip().lower())


class Registry:
    """Loaded company registry with canonical-name + blacklist resolution."""

    def __init__(self, entries: list[dict]):
        self.entries: list[dict] = [e for e in entries if isinstance(e, dict)]
        self._key_to_canonical: dict[str, str] = {}
        self._canonical_to_keys: dict[str, set[str]] = {}
        self._blacklist: dict[str, str] = {}   # canonical name -> reason
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
            if entry.get("blacklist"):
                reason = entry["blacklist"]
                self._blacklist[canonical] = reason if isinstance(reason, str) else ""

    # ---- resolution -------------------------------------------------------- #
    def canonical(self, raw: str | None) -> str | None:
        """Map a raw company string to its canonical display name, else None."""
        return self._key_to_canonical.get(normalize(raw))

    def match_keys(self, raw: str | None) -> set[str]:
        """All normalized match keys for the company `raw` resolves to.

        Falls back to the single normalized raw string when unknown, so callers
        can match aggregator-only companies not present in the registry.
        """
        canonical = self.canonical(raw)
        if canonical is not None:
            return set(self._canonical_to_keys.get(canonical, set()))
        norm = normalize(raw)
        return {norm} if norm else set()

    def is_blacklisted(self, raw: str | None) -> tuple[bool, str | None]:
        """(True, reason) if `raw` resolves to a blacklisted company, else (False, None)."""
        canonical = self.canonical(raw)
        if canonical is not None and canonical in self._blacklist:
            return True, self._blacklist[canonical] or None
        return False, None

    def blacklisted_keys(self) -> set[str]:
        """Every normalized match key belonging to a blacklisted company."""
        keys: set[str] = set()
        for canonical in self._blacklist:
            keys |= self._canonical_to_keys.get(canonical, set())
        return keys

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
        return keys

    # ---- polling ----------------------------------------------------------- #
    def poll_companies(self, tags: list[str] | None = None) -> list[dict]:
        """Entries with an `ats` (identity-only rows excluded), tag-filtered."""
        pollable = [e for e in self.entries if e.get("ats")]
        if not tags:
            return pollable
        tagset = {t.strip().lower() for t in tags}
        return [c for c in pollable
                if tagset & {str(t).lower() for t in (c.get("tags") or [])}]


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
    bases.append(SKILL_DIR.parents[2])  # .agents/skills/job-search -> repo root

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
