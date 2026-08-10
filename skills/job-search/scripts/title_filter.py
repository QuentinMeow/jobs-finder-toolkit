"""Profile-owned title word classes for the coarse title filter.

WHY THIS MODULE EXISTS
----------------------
The coarse title prefilter in ``sources.py`` used to carry a hardcoded tuple of
skip words. Five of them (``principal``, ``distinguished``, ``fellow``,
``data scientist``, ``research scientist``) encoded a SENIORITY/DISCIPLINE policy
that the candidate's search profile is supposed to own, so a profile that
deliberately targets those roles received none of them from the big-tech boards
— silently, with no filtered row and no count. Owner decision (2026-08-01):
make the whole list profile-based, because different candidates want different
filters, and give it three classes instead of one.

THE THREE CLASSES (all live in the candidate's own search profile, under
``titles.word_filter``; the profile file itself is reached through
``config.search_profiles_dir()`` — never a path literal, never a list in code):

``hard_exclude``
    Always drop. A hit removes the posting before it costs anything: on the
    big-tech boards that means before its per-posting detail fetch, and on every
    other source at the first pipeline gate. The drop is COUNTED in the run
    summary, so "always drop" is never "drop without saying so".

``soft_exclude``
    Never drop on title. The word is suspicious, not disqualifying — ``manager``
    is a report line in one title and a product name in another ("Software
    Engineer, Manager Tools") — so the posting is KEPT and MARKED, and the
    marking is what makes the downstream AI step open the JD and decide.

``include``
    Never drop on title, and the same marking: a hit means "we must check this
    one out". It is the positive twin of ``soft_exclude`` — the candidate names a
    word whose postings must reach judgement even when the ordinary title gate
    would have thrown them away.

PRECEDENCE — ``hard_exclude`` > ``include`` > ``soft_exclude``
    The owner's word for ``hard_exclude`` is *always*, and it is the only class
    with an unconditional contract; an ``include`` word cannot rescue a title the
    candidate declared always-unwanted. The collision is not silent: listing one
    word in two classes produces a load-time warning naming the word and the
    winner (see :func:`load_word_lists`), so a mistake surfaces when the profile
    is read rather than as a missing posting weeks later. ``include`` outranks
    ``soft_exclude`` only in which reason is reported first — both route to the
    same review action.

MATCHING — case-insensitive, bounded phrase, never a bare substring
    Reuses ``common.bounded_phrase_re``, the idiom the rest of this skill already
    matches lexicon phrases with, so the classes behave like every other phrase
    list here:

    * ``intern`` does NOT match *Internal Developer Platform* or
      *Internationalization*; ``director`` does not match *Active Directory*;
      ``sales`` does not match *Salesforce Platform*.
    * A short trailing English inflection (``s/es/d/ed/ing/er/ers``) still counts,
      so ``recruit`` matches *Recruiter* and *Recruiting Coordinator* — which is
      the entire reason a candidate writes ``recruit`` rather than three spellings.
      ``-ment`` is not an inflection, so **``manager`` does not match
      *management***, and ``-al`` is not one either, so ``intern`` does not match
      *Internal*.
    * A LEADING or TRAILING SPACE in a configured word is load-bearing, not stray
      formatting: it asks for literal whitespace on that edge, which is STRICTER
      than a word boundary because it also refuses a match glued to punctuation.
      ``" manager"`` drops *Engineering Manager* while keeping *Software Engineer
      (Manager Tools)* and *Lead Software Engineer/Manager*. The title is padded
      before matching so the start and end of the string count as that whitespace.

DEGRADATION — missing or empty config is INERT, never a hidden default
    A profile with no ``titles.word_filter`` block (or one whose three lists are
    all empty) classifies every title as ``keep``: the coarse filter does nothing
    and ``scoring.assess_title`` — the profile's own ``titles.include`` /
    ``titles.exclude`` gate — decides alone, exactly as it would have without this
    module. That is the only degradation compatible with "not hardcoded in code":
    a built-in fallback list would put the policy back where the owner took it
    from. It is also the recall-safe direction — nothing is dropped that was not
    asked to be dropped. The cost is a wider (slower) fetch against the
    candidate-capped big-tech boards, so ``search_jobs.py`` prints a one-line
    notice naming the key when a profile has not configured it.

Stdlib + this skill's own ``common`` module only.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from common import bounded_phrase_re

# Profile keys. ``titles.word_filter`` is nested rather than flat because
# ``titles.include`` / ``titles.exclude`` already exist and mean something else
# (the pipeline's title gate); reusing either name would silently merge two rules.
TITLES_KEY = "titles"
WORD_FILTER_KEY = "word_filter"
HARD_EXCLUDE = "hard_exclude"
SOFT_EXCLUDE = "soft_exclude"
INCLUDE = "include"
CLASSES = (HARD_EXCLUDE, INCLUDE, SOFT_EXCLUDE)   # in precedence order

# Verdict actions.
ACTION_DROP = "drop"       # hard_exclude hit: remove before it costs anything
ACTION_REVIEW = "review"   # soft_exclude / include hit: keep, mark, let the AI judge
ACTION_KEEP = "keep"       # no hit: the ordinary title gate decides alone


def _normalize_word(word) -> str:
    """Lowercase + collapse internal whitespace, PRESERVING the edge spaces.

    The edges are the rule (see the module docstring), so this deliberately does
    not strip: ``" manager"`` must stay ``" manager"``.
    """
    return re.sub(r"\s+", " ", str(word).lower())


def _normalize_title(title: str | None) -> str:
    """Whitespace-normalise and PAD a title so edge spaces can match.

    Padding makes the start and end of the string count as the literal whitespace
    a space-padded word asks for, and normalising means a board that emits a tab
    or a non-breaking space is matched like one that emits a space. It is a no-op
    for every unpadded word: their own edges are alphanumeric, so they carry
    ``bounded_phrase_re``'s boundary assertion instead.
    """
    return " %s " % re.sub(r"\s+", " ", (title or "").lower()).strip()


@dataclass(frozen=True)
class TitleVerdict:
    """What the three classes say about one title.

    ``action`` is the only field the pipeline branches on; the per-class hits are
    carried so every consequence can name the word that caused it.
    """

    action: str
    hard_hits: tuple[str, ...] = ()
    include_hits: tuple[str, ...] = ()
    soft_hits: tuple[str, ...] = ()

    @property
    def review_reasons(self) -> list[str]:
        """Machine tokens for ``JobPosting.review_reasons`` (the review queue key)."""
        return ([f"title_include_signal:{w.strip()}" for w in self.include_hits]
                + [f"title_soft_excluded:{w.strip()}" for w in self.soft_hits])

    @property
    def reason_notes(self) -> list[str]:
        """Human-readable notes appended to a surfaced row's ``reasons``.

        A ``review`` verdict must not be a SILENT keep any more than it may be a
        silent drop, so whichever list the posting lands on, its row says which
        configured word demands a look.

        Kept SHORT on purpose: the discovery table truncates its reasons column at
        100 characters, and a note that is cut off tells the reader nothing.
        """
        notes = []
        if self.include_hits:
            notes.append("title include signal: "
                         + ", ".join(w.strip() for w in self.include_hits)
                         + " (read the JD)")
        if self.soft_hits:
            notes.append("title soft-exclude: "
                         + ", ".join(w.strip() for w in self.soft_hits)
                         + " (read the JD)")
        return notes


@dataclass(frozen=True)
class TitleWordFilter:
    """The candidate's three word lists, compiled once per run.

    Constructed with no arguments this is the INERT filter: every title keeps,
    which is what an unconfigured profile gets (see the module docstring).
    """

    hard_exclude: tuple[str, ...] = ()
    include: tuple[str, ...] = ()
    soft_exclude: tuple[str, ...] = ()
    warnings: tuple[str, ...] = field(default=())

    @property
    def configured(self) -> bool:
        return bool(self.hard_exclude or self.include or self.soft_exclude)

    def _hits(self, padded_title: str, words: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(w for w in words if bounded_phrase_re(w).search(padded_title))

    def classify(self, title: str | None) -> TitleVerdict:
        """Classify one title. Pure function of the title and the three lists."""
        if not self.configured:
            return TitleVerdict(ACTION_KEEP)
        padded = _normalize_title(title)
        if not padded.strip():
            # A blank title carries no evidence either way; the ordinary gates
            # (including the unfilled-template check) still see it.
            return TitleVerdict(ACTION_KEEP)
        hard = self._hits(padded, self.hard_exclude)
        if hard:
            # Precedence: hard wins outright, so include/soft hits are not even
            # collected — reporting them would suggest the drop was negotiable.
            return TitleVerdict(ACTION_DROP, hard_hits=hard)
        include = self._hits(padded, self.include)
        soft = self._hits(padded, self.soft_exclude)
        if include or soft:
            return TitleVerdict(ACTION_REVIEW, include_hits=include, soft_hits=soft)
        return TitleVerdict(ACTION_KEEP)

    def prefilter(self, title: str | None) -> bool:
        """True when a title is worth its (expensive) per-posting detail fetch.

        Only ``hard_exclude`` answers False. ``soft_exclude`` and ``include`` mean
        "fetch it and let the JD decide", which is the whole point of those two
        classes — a title dropped here is never fetched, so it leaves no filtered
        row and no snapshot trace, and that silent shape is what this module exists
        to remove.
        """
        return self.classify(title).action != ACTION_DROP


INERT = TitleWordFilter()


def load_word_lists(profile: dict | None) -> TitleWordFilter:
    """Build the filter from a loaded search profile's ``titles.word_filter``.

    Missing block, missing keys, empty lists and non-list values all degrade to
    the inert filter rather than to a built-in list (see the module docstring).
    A word listed in more than one class is reported in ``warnings`` naming the
    winner, so the precedence rule is visible at load time. The same is done for
    the CROSS-BLOCK collision that used to be invisible: a word in both
    ``titles.exclude`` and this block's ``include``/``soft_exclude``
    (see :func:`_cross_block_warnings`).
    """
    raw = (((profile or {}).get(TITLES_KEY) or {}).get(WORD_FILTER_KEY) or {})
    if not isinstance(raw, dict):
        return TitleWordFilter(warnings=(
            f"{TITLES_KEY}.{WORD_FILTER_KEY} is not a mapping "
            f"({type(raw).__name__}); the coarse title filter is inert this run.",))

    lists: dict[str, tuple[str, ...]] = {}
    warnings: list[str] = []
    for name in CLASSES:
        value = raw.get(name)
        if value is None:
            lists[name] = ()
            continue
        if isinstance(value, str) or not isinstance(value, (list, tuple)):
            warnings.append(
                f"{TITLES_KEY}.{WORD_FILTER_KEY}.{name} must be a list of words "
                f"(got {type(value).__name__}); treating it as empty.")
            lists[name] = ()
            continue
        seen: dict[str, None] = {}
        for word in value:
            if word is None:
                # A bare `- ` row in YAML. Coercing it would add the literal word
                # "none" to the list, which would then match real titles.
                continue
            normalized = _normalize_word(word)
            if normalized.strip():
                seen.setdefault(normalized, None)
        lists[name] = tuple(seen)

    # Cross-class collisions, reported in precedence order. Compared on the
    # STRIPPED word so " manager" and "manager" are recognised as the same word
    # in two classes rather than passing as two unrelated entries.
    owner: dict[str, str] = {}
    for name in CLASSES:
        for word in lists[name]:
            key = word.strip()
            if key in owner:
                warnings.append(
                    f"{TITLES_KEY}.{WORD_FILTER_KEY}: {key!r} is listed in both "
                    f"{owner[key]} and {name}; {owner[key]} wins "
                    f"(precedence: {' > '.join(CLASSES)}).")
            else:
                owner[key] = name

    warnings.extend(_cross_block_warnings(profile, lists))

    return TitleWordFilter(
        hard_exclude=lists[HARD_EXCLUDE],
        include=lists[INCLUDE],
        soft_exclude=lists[SOFT_EXCLUDE],
        warnings=tuple(warnings),
    )


# The two rescue classes. Both KEEP a title the ordinary gate would have thrown
# away (see `search_jobs.filter_score_rank`: a `review` verdict sets
# `title_flagged`, and a flagged row that `title_ok` rejects is rescued to the
# review queue instead of dropped), so a word in either of them CONTRADICTS the
# same word in `titles.exclude` rather than merely duplicating it.
_RESCUE_CLASSES = (INCLUDE, SOFT_EXCLUDE)
EXCLUDE_KEY = "exclude"


def _cross_block_warnings(profile: dict | None,
                          lists: dict[str, tuple[str, ...]]) -> list[str]:
    """Warn when a word is in BOTH ``titles.exclude`` and a rescue class here.

    The in-block collision check above only sees the three ``word_filter``
    classes, so the sharper contradiction was silent: ``titles.exclude`` says
    "drop this title" while ``word_filter.soft_exclude``/``include`` says "never
    drop it, mark it for judgement". They cannot both hold, and the word_filter
    is the one that runs later and wins — the posting reaches the review queue
    and the profile's own exclude never takes effect for it. Reporting it at load
    time is the difference between a visible policy choice and a profile that
    quietly contradicts itself.
    """
    titles = ((profile or {}).get(TITLES_KEY) or {})
    raw_excludes = titles.get(EXCLUDE_KEY)
    if not isinstance(raw_excludes, (list, tuple)):
        return []
    excludes: dict[str, None] = {}
    for term in raw_excludes:
        if term is None:
            continue
        key = _normalize_word(term).strip()
        if key:
            excludes.setdefault(key, None)

    out: list[str] = []
    for name in _RESCUE_CLASSES:
        for word in lists.get(name, ()):
            key = word.strip()
            if key in excludes:
                out.append(
                    f"{TITLES_KEY}: {key!r} is listed in both "
                    f"{TITLES_KEY}.{EXCLUDE_KEY} and "
                    f"{TITLES_KEY}.{WORD_FILTER_KEY}.{name}; "
                    f"{TITLES_KEY}.{WORD_FILTER_KEY}.{name} wins — the posting is "
                    f"kept and sent to review, so {TITLES_KEY}.{EXCLUDE_KEY} never "
                    f"drops it.")
    return out
