#!/usr/bin/env python3
"""The owner's company index — one stable key per employer, and its linter.

The index is a private, owner-owned YAML mapping ``key -> {display, aliases[],
kind, parent?}`` at :data:`DEFAULT_REL`. This module is the PUBLIC half: the file
format, the loader, the linter, and the exact-match resolver. It ships with no
data and never reads anything but the path it is handed, so it is inert in any
checkout without the overlay.

WHAT THE KEY IS FOR, AND WHAT IT MUST NEVER DO
----------------------------------------------
A key answers one question — "which employer is this?" — for FILING and
NAVIGATION. It is deliberately **not** a matching primitive:

  * it never enters a skip, dedup, filter or coverage comparison. Those keep
    reading the free-text ``company`` string through their own normalizers;
  * on a filing path a wrong key costs a mislabelled report. On a match path it
    would silently re-draft an application to an employer that already said no
    (an alias *split*), or silently suppress a genuinely new posting (an alias
    *merge*). The keys are hand-assigned in one review pass, so they are the
    least-verified data in the tree — and you do not put your least-verified data
    on your most consequential path.

:func:`resolve` is therefore exact-match only over ``{key} u {display} u aliases``,
normalized. No suffix stripping, no fuzzy fallback: a fallback would let a wrong
key look right, and abstaining is the same behaviour the company registry's own
ambiguity handling already has. A string that does not resolve is reported as
unkeyed, which is a number a human reads — never a silent wrong answer.

FILE FORMAT
-----------
::

    acme-labs:
      display: Acme Labs
      aliases: [Acme Labs Inc., Acme Research]
      kind: employer
    acme-cloud:
      display: Acme Cloud
      kind: employer
      parent: acme-labs

``display`` and ``kind`` are required; ``aliases`` and ``parent`` are optional.
Casing of ``display``/``aliases`` is DISPLAY casing — the advisory detector in
``automation/publish/review_gate.py`` prints them verbatim and lowercases only at
comparison time, so a lowercased alias would print as noise.

TWO TRAPS THIS LINTER EXISTS FOR
--------------------------------
1. **PyYAML types plain scalar keys.** An unquoted ``on:`` / ``no:`` / ``yes:`` /
   ``off:`` / ``y:`` / ``n:`` top-level key is resolved to a Python ``bool``
   BEFORE :data:`KEY_RE` ever sees a string — YAML 1.1 booleans. Same class of bug
   that forced ``review_gate._LedgerLoader``. Hence the "every top-level key is a
   str" rule, and hence :func:`from_raw` drops such an entry instead of stringifying
   it into a key that was never written.
2. **The advisory detector does a plain substring test.**
   ``review_gate.company_hints`` computes ``[n for n in names if n.lower() in added]``
   over the whole added-lines blob of a diff, so an alias that is also an ordinary
   English word fires on unrelated code — and a diff the detector fired on must be
   signed ``reviewed_by: human``, which trains the reader to rubber-stamp the one
   signal that matters. Hence the two alias rules below.

THE TWO ALIAS RULES, AND THE TWO THAT WERE TRIED AND WITHDRAWN
---------------------------------------------------------------
Measured, not reasoned. Running the detector over three real commit ranges with a
real index (223 keys / 270 distinct display+alias strings) produced:

  * **a reproduced false positive** — a four-letter alias that is an ordinary word
    matched a code COMMENT that happened to use that word;
  * **a noise floor with a sharp edge** — only names ABSENT from the public tree can
    ever fire. The baseline subtraction at ``review_gate.py:470-471`` greps the tree
    at the range's base, so a name already written anywhere public is subtracted
    from then on; 149 of those 270 real names were already subtracted that way. It
    follows that the FIRST diff to introduce a colliding word gets a spurious hint
    and every later one is silent;
  * **latency is a non-issue** — 0.21s to 0.56s per range, because the per-name
    ``git grep`` only runs for names whose lowercase already appears in the diff.

**Rule 1 — an ALL-LOWERCASE single-token alias that is a substring of its own
display is rejected.** That is the shape every measured offender had: a lowercase
shortening of a dotted or two-word name, mined from a log that stores aliases
normalized. All three conditions are load-bearing, and the first was added after the
rule without it rejected a legitimate alias in a real index:

  * *all-lowercase* — aliases are display-cased by convention (the detector prints
    them verbatim), so an all-lowercase one is a normalization artifact rather than
    a spelling a human writes. A display-cased short form survives;
  * *single token* — only a bare token substring-matches ordinary prose;
  * *substring of the display* — a truncation carries no spelling the display does
    not already carry. An abbreviation or an initialism is not a substring of the
    name it shortens, so both survive.

The rule is STRUCTURAL: it publishes no vocabulary, so it cannot be read backwards
into anyone's index and it cannot blind the detector (below).

**Rule 2 — :data:`ALIAS_STOP_LIST` is HYGIENE, not noise-suppression**, and saying
so is more useful than overclaiming. Because the detector subtracts any name already
present in the public tree, and this list is constrained to words this repo already
uses, an alias equal to a token on it could not have fired anyway. What the rule buys
is that an alias indistinguishable from this repository's own vocabulary is a poor
identity token, and it is one edit away from the collision rule 1 exists for. The
noise-suppression job belongs to rule 1.

Three drafts were narrowed or withdrawn BY MEASUREMENT rather than by argument. Each
is named by a guard test, so a future tightening cannot quietly reinstate it:

  * **rule 1 without the lowercase condition.** It rejected a legitimate alias in a
    real index — the display-cased first word of a two-word employer name, which is
    the short form a human writes and which a ``company:`` string may genuinely
    carry, so dropping it would leave that application unkeyed. Guard:
    ``test_display_cased_short_form_alias_is_not_a_finding``;

  * **a minimum alias length.** Length 5 destroyed two legitimate, high-value short
    aliases (a three-letter divisional acronym and a three-character ampersand
    initialism, both from the richest alias source in the repo) while still missing
    two five-character offenders. **Short is not the problem; ordinary is.** Guard:
    ``test_short_abbreviation_alias_is_not_a_finding``;
  * **a general English-word dictionary in the stop-list.** Tried at ~620 tokens;
    149 of them appeared nowhere in the public tree. Publishing a word here PUTS it
    in the public tree, so the baseline grep would subtract it from then on and
    **the detector would stop hinting on any employer whose name is that word.** A
    noise-reduction list that blinds the detector to 149 names costs far more than
    it saves. Hence the stop-list holds only vocabulary this repository already
    uses. Guard: ``test_stop_list_holds_no_vocabulary_new_to_this_repo``.

Both rules apply to ``aliases`` ONLY, never to ``display``. A short or ordinary
display name is the employer's real name: it cannot be lengthened or dropped
without lying, and it is normally already somewhere in the public tree and so
already subtracted. Guard: ``test_short_display_name_is_not_a_finding``.

Standard library plus ``yaml`` only.
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

# The single source for this literal. ``review_gate.COMPANY_INDEX_REL`` restates it
# (a gate must not gain an import it can fail on) and a test pins the two together.
# It is NOT routed through ``config.companies_root()`` on purpose — see review_gate.
DEFAULT_REL = "private/companies/_index.yaml"

# Same shape as ``job_metadata._STORE_KEY_RE``: usable as a folder name and as a URL
# fragment, which is what the key is actually spent on.
KEY_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")

# ``interview_vendor`` is a firm that RUNS an interview rather than one that hires:
# its artifacts belong to some other employer's application, so a report must be
# able to tell the two apart.
KINDS = frozenset({"employer", "interview_vendor"})

# Fields an entry may carry. Closed on purpose: a typo'd ``alias:`` would silently
# drop that employer's spellings from the leak detector's token set, and nothing
# else in the repo reads this file closely enough to notice.
FIELDS = ("display", "aliases", "kind", "parent")

# Subject used for a problem with the file as a whole rather than one entry.
FILE_SUBJECT = "<file>"

# Ordinary words that are NOT truncations of their display (rule 1 catches those).
#
# This rule is HYGIENE, NOT NOISE-SUPPRESSION, and the distinction is the whole
# point of constraint 1 below: because every token here is required to be
# vocabulary the public tree already contains, the detector would have subtracted
# it anyway (review_gate.py:470-471) and it could never have fired. What the rule
# actually buys is that an alias which is a bare programming term is a modelling
# mistake — it says nothing about which employer is meant — and it is caught at
# lint time rather than lived with.
#
# TWO CONSTRAINTS ON WHAT MAY GO IN HERE, both load-bearing:
#
# 1. Every token must be vocabulary THIS REPOSITORY ALREADY USES. Publishing a
#    word here puts it in the public tree, and the detector permanently subtracts
#    every name already in the public tree (review_gate.py:470-471) — so a word
#    that is new to this repo would blind the detector to any employer of that
#    name, in exchange for suppressing a false positive that this repo's own
#    diffs cannot produce in the first place. A ~620-token English dictionary was
#    tried; 149 of its tokens were new to the tree, and it was withdrawn for
#    exactly this reason. Verified: every token below already occurs in the
#    public tree.
# 2. Every token is here because it is a generic programming or repo term, NEVER
#    as a record of which employer's alias collided. A list that could be read
#    backwards into an employer list would be the leak this file exists to
#    prevent.
#
# The first four are measured: ``review_gate.company_display_names``' docstring
# records that they alone matched 51 of 177 private company tokens across the
# public tree.
ALIAS_STOP_LIST = frozenset({
    "canonical", "writer", "render", "lambda",
    "agent", "agents", "alias", "aliases", "assert", "async", "await",
    "binary", "bool", "branch", "buffer", "build", "bytes", "cache",
    "canonical", "check", "class", "client", "cluster", "commit", "company",
    "config", "const", "context", "count", "debug", "default", "diff",
    "docs", "elif", "else", "encode", "enum", "error", "event", "except",
    "exec", "false", "fetch", "field", "file", "filter", "finally", "float",
    "format", "global", "graph", "handler", "hash", "header", "hook",
    "hooks", "import", "index", "init", "input", "integer", "json", "keys",
    "kwargs", "label", "lambda", "ledger", "level", "lint", "list", "load",
    "local", "main", "match", "merge", "metric", "model", "module", "node",
    "none", "normalize", "null", "object", "option", "output", "parse",
    "parser", "patch", "path", "payload", "pointer", "print", "private",
    "profile", "public", "python", "query", "queue", "range", "record",
    "regex", "render", "repo", "request", "resume", "return", "review",
    "root", "route", "runner", "schema", "scope", "script", "search",
    "server", "session", "shared", "skill", "skills", "slug", "snapshot",
    "source", "stack", "stage", "state", "status", "stdout", "store",
    "stream", "string", "struct", "stub", "style", "suite", "sync",
    "syntax", "table", "target", "task", "tasks", "test", "tests", "text",
    "thread", "token", "trace", "true", "tuple", "type", "value", "vendor",
    "worker", "write", "writer", "yaml", "yield",
})

@dataclass(frozen=True)
class Entry:
    """One employer. ``aliases`` is a tuple so an ``Entry`` stays hashable."""

    key: str
    display: str
    aliases: tuple[str, ...]
    kind: str
    parent: str | None


def normalize(value: Any) -> str:
    """Comparison form: whitespace collapsed, case folded.

    Case folding is the axis the advisory detector compares on (``n.lower() in
    added``), so two spellings that differ only in case are one name here too.
    """
    if not isinstance(value, str):
        return ""
    return " ".join(value.split()).casefold()


# ── loading ──────────────────────────────────────────────────────────────────

def read_raw(path: str | Path) -> Any:
    """The parsed YAML at ``path``; ``{}`` when the file is absent.

    Malformed YAML PROPAGATES (``yaml.YAMLError``). A silent empty index would
    read as "this owner has no companies", which is indistinguishable from a clean
    file and is exactly the failure the detector's ``None`` return exists to avoid.
    """
    p = Path(path)
    if not p.is_file():
        return {}
    return yaml.safe_load(p.read_text(encoding="utf-8"))


def from_raw(raw: Any) -> dict[str, Entry]:
    """Build the index from parsed YAML, skipping rows that are not usable.

    Permissive on purpose: :func:`lint` is the judge and reports every defect,
    while this function's job is to hand back whatever is well-formed enough to
    resolve against. A row with a non-string key, a non-mapping body or a blank
    ``display`` is dropped rather than guessed at.
    """
    index: dict[str, Entry] = {}
    if not isinstance(raw, Mapping):
        return index
    for key, body in raw.items():
        if not isinstance(key, str) or not isinstance(body, Mapping):
            continue
        display = body.get("display")
        if not isinstance(display, str) or not display.strip():
            continue
        raw_aliases = body.get("aliases")
        aliases = tuple(
            a.strip() for a in raw_aliases
            if isinstance(a, str) and a.strip()
        ) if isinstance(raw_aliases, list) else ()
        kind = body.get("kind")
        parent = body.get("parent")
        index[key] = Entry(
            key=key,
            display=display.strip(),
            aliases=aliases,
            kind=kind if isinstance(kind, str) else "",
            parent=parent if isinstance(parent, str) and parent.strip() else None,
        )
    return index


def load(path: str | Path) -> dict[str, Entry]:
    """``from_raw(read_raw(path))``. Absent file -> ``{}``; bad YAML propagates."""
    return from_raw(read_raw(path))


# ── resolution ───────────────────────────────────────────────────────────────

def lookup_table(index: Mapping[str, Entry]) -> dict[str, str]:
    """Normalized string -> key, over ``{key} u {display} u aliases``.

    Collisions are a lint finding, so a linted index builds a total function. In an
    UNLINTED one the first entry in file order wins, which is the same
    first-writer-wins behaviour the public registry already has.
    """
    table: dict[str, str] = {}
    for key, entry in index.items():
        for raw in (key, entry.display, *entry.aliases):
            norm = normalize(raw)
            if norm and norm not in table:
                table[norm] = key
    return table


def resolve(index: Mapping[str, Entry], raw: str) -> str | None:
    """The key ``raw`` names, or ``None``.

    Exact normalized match only. Abstaining is the point: a fuzzy fallback would
    let a wrong key look right, and an unresolved string is reported as a number
    rather than acted on.
    """
    return lookup_table(index).get(normalize(raw))


# ── the linter ───────────────────────────────────────────────────────────────

def _alias_findings(key: str, body: Mapping[Any, Any]) -> list[tuple[str, str]]:
    """Per-entry alias rules: type, duplicates, the truncation rule, the stop-list.

    There is deliberately NO length rule — see the module docstring, and the guard
    test named there.
    """
    out: list[tuple[str, str]] = []
    raw_aliases = body.get("aliases")
    if raw_aliases is None:
        return out
    if not isinstance(raw_aliases, list):
        return [(key, f"aliases must be a list, got {type(raw_aliases).__name__}")]

    display = body.get("display")
    display_norm = normalize(display) if isinstance(display, str) else ""

    seen: set[str] = set()
    for alias in raw_aliases:
        if not isinstance(alias, str) or not alias.strip():
            out.append((key, f"alias must be a non-empty string, got {alias!r}"))
            continue
        text = alias.strip()
        norm = normalize(text)
        if norm in seen:
            out.append((key, f"alias {text!r} is listed twice in this entry"))
            continue
        seen.add(norm)
        # Rule 1 — an ALL-LOWERCASE single-token truncation of the display. Three
        # conditions, and dropping any one of them rejects a legitimate alias:
        # lowercase (aliases are display-cased by convention, so an all-lowercase one
        # is a log-normalized artifact rather than a spelling anyone writes), one
        # token (only a bare token collides with prose), and already contained in the
        # display (so it adds no spelling). A display-cased short form, an
        # abbreviation and an initialism all survive.
        if (text.islower() and len(text.split()) == 1
                and display_norm and norm in display_norm):
            out.append((key, f"alias {text!r} is an all-lowercase single-token "
                             f"shortening of its own display name ({display!r}). "
                             "Aliases are display-cased by convention, so this is a "
                             "log-normalized artifact: it adds no spelling the display "
                             "does not already carry, and a bare lowercase token "
                             "substring-matches ordinary prose, firing the advisory "
                             "leak detector on unrelated diffs. Drop it, or write it "
                             "in the casing a human would"))
            continue
        # Rule 2 — an ordinary word that is NOT a truncation (an acquired brand or a
        # rebrand that happens to be common vocabulary).
        if norm in ALIAS_STOP_LIST:
            out.append((key, f"alias {text!r} is a generic word this repository already "
                             "uses in its own code and prose — the advisory leak detector "
                             "substring-matches aliases against whole diffs, so it would "
                             "fire on unrelated changes. Use a longer, more specific "
                             "spelling, or drop it"))
    return out


def _entry_findings(key: str, body: Mapping[Any, Any]) -> list[tuple[str, str]]:
    """Per-entry field rules: unknown fields, display, kind, parent shape."""
    out: list[tuple[str, str]] = []

    unknown = sorted(str(f) for f in body if f not in FIELDS)
    if unknown:
        out.append((key, "unknown field(s): " + ", ".join(unknown)
                    + f" (allowed: {', '.join(FIELDS)})"))

    display = body.get("display")
    if not isinstance(display, str) or not display.strip():
        out.append((key, f"display is required and must be a non-empty string, "
                         f"got {display!r}"))

    kind = body.get("kind")
    if not isinstance(kind, str) or kind not in KINDS:
        out.append((key, f"kind must be one of {sorted(KINDS)}, got {kind!r}"))

    parent = body.get("parent")
    if parent is not None and (not isinstance(parent, str) or not parent.strip()):
        out.append((key, f"parent must be a non-empty string when present, got {parent!r}"))
    elif isinstance(parent, str) and parent.strip() == key:
        out.append((key, "an entry cannot be its own parent"))

    out.extend(_alias_findings(key, body))
    return out


def _parent_findings(index: Mapping[str, Entry]) -> list[tuple[str, str]]:
    """``parent`` resolves to another key, and no chain of parents cycles.

    Nothing public READS ``parent``, so a broken one is invisible to every other
    check in the repo — which is precisely why it is linted here.
    """
    out: list[tuple[str, str]] = []
    for key, entry in index.items():
        if entry.parent is None or entry.parent == key:
            continue          # self-parent already reported by _entry_findings
        if entry.parent not in index:
            out.append((key, f"parent {entry.parent!r} is not a key in this index"))

    for key in index:
        chain = [key]
        seen = {key}
        cursor = index[key].parent
        while cursor is not None and cursor in index and cursor not in seen:
            chain.append(cursor)
            seen.add(cursor)
            cursor = index[cursor].parent
        if cursor is not None and cursor in seen:
            cycle = chain[chain.index(cursor):]
            # One finding per cycle, not one per member: report it from the
            # lexicographically smallest member so the output is deterministic.
            if key == min(cycle):
                out.append((key, "parent chain forms a cycle: "
                                 + " -> ".join([*cycle, cycle[0]])))
    return out


def _collision_findings(index: Mapping[str, Entry]) -> list[tuple[str, str]]:
    """No alias is claimed twice, and no alias is another entry's key or display.

    All three are the same collision by different spellings, and any of them makes
    :func:`resolve` a coin flip decided by file order.
    """
    out: list[tuple[str, str]] = []
    by_key = {normalize(key): key for key in index}
    by_display: dict[str, str] = {}
    for key, entry in index.items():
        by_display.setdefault(normalize(entry.display), key)

    alias_owner: dict[str, str] = {}
    for key, entry in index.items():
        for alias in entry.aliases:
            norm = normalize(alias)
            if not norm:
                continue
            owner = alias_owner.get(norm)
            if owner is not None and owner != key:
                out.append((key, f"alias {alias!r} is already claimed by {owner!r}"))
                continue
            alias_owner[norm] = key
            other = by_key.get(norm)
            if other is not None and other != key:
                out.append((key, f"alias {alias!r} is another entry's key ({other!r})"))
            other = by_display.get(norm)
            if other is not None and other != key:
                out.append((key, f"alias {alias!r} is another entry's display name "
                                 f"({other!r})"))
    return out


def lint(raw: Any) -> list[tuple[str, str]]:
    """Every defect in a parsed index, as ``(subject, message)`` pairs.

    Exactly the shape ``sync_skill_manifests.findings()`` returns, so the
    reconciler adapter around it is three lines. ``subject`` is the entry key —
    or :data:`FILE_SUBJECT` for a problem with the file as a whole.
    """
    if raw is None:
        raw = {}
    if not isinstance(raw, Mapping):
        return [(FILE_SUBJECT,
                 "the index must be a mapping of key -> entry, "
                 f"got {type(raw).__name__}")]

    out: list[tuple[str, str]] = []
    for key, body in raw.items():
        if not isinstance(key, str):
            out.append((repr(key),
                        "top-level keys must be strings, and this one is a "
                        f"{type(key).__name__} — PyYAML resolves plain scalar keys, so an "
                        "unquoted on/off/yes/no/y/n key becomes a YAML 1.1 boolean before "
                        "any check sees a string. Quote it."))
            continue
        if not KEY_RE.match(key):
            out.append((key, f"key must match {KEY_RE.pattern} (lowercase, digits and "
                             "hyphens; it is used as a folder name and a URL fragment)"))
        if not isinstance(body, Mapping):
            out.append((key, f"entry must be a mapping, got {type(body).__name__}"))
            continue
        out.extend(_entry_findings(key, body))

    index = from_raw(raw)
    out.extend(_parent_findings(index))
    out.extend(_collision_findings(index))
    return out
