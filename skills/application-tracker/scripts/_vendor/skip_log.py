"""Append-only event log of postings already generated or considered (the skip-log).

The YAML skip-log this replaces was a *projection*: ``status.py --sync-log``
rebuilt it wholesale from a scan of the application folders. Delete a rejected
application — an ordinary thing for an owner to do — re-sync, and that posting's
row is gone, so job-search re-surfaces the posting as fresh. This file is the
opposite shape: one JSON object per line, one line per event, and the only write
is an append. Truncation is not a policy that could be relaxed; it is structurally
absent. A key with no matching folder is simply left alone.

That makes the file **authoritative rather than derived**: nothing regenerates it
from anything, so a lost or corrupted file is recovered from git history, never by
re-running a sync.

**The fold is in FILE ORDER, last wins. Nothing sorts on ``recorded``.** In an
append-only file the byte position of a line already IS its causal order, while
``recorded`` is a second-granularity wall clock that can run backwards — an NTP
step or a resume-from-suspend between two syncs is enough. Sort on it and the
older event wins, leaving readers on a stale status with no sign anything is
wrong. ``recorded`` exists to be read by a human and for nothing else.

**``fold_key`` deduplicates INSIDE this file and is never a reader's match key.**
Readers keep their own normalizers, their own key construction, and their own
registry expansion verbatim; they only swap where the row list comes from. That
matters because this module's identity is deliberately *wider* than, say,
``search_jobs._norm_url`` (it also collapses internal whitespace) and because
``search_jobs.load_considered`` derives a URL key AND a ``(company, role)`` key
from every row via two independent ``if``s, not an if/else. A wider identity here
only means fewer duplicate lines in the file; the same widening applied inside a
reader, to one side of a comparison, silently loses skips. Hence
:func:`read_postings` hands back rows in exactly the shape the YAML ``postings``
entries had, so every consumer's parsing code keeps working untouched.

This module does **not** import ``automation/shared/store/atomic.py``, whose
``append_line`` does the same job. ``skills/application-tracker/scripts/_vendor/``
has no ``store/``, and adding one to the vendoring ``DIR_TARGETS`` would copy the
whole store package — schemas, migrations, ~20 files — into a skill that needs one
function. The dozen duplicated lines below are the cheaper of the two costs.

Standard library only: this file is vendored byte-identically into the job-search
and application-tracker skills, which must run with no repo-root imports.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

# The exact key set the YAML ``postings`` rows carried (status.py ``build_log``).
# :func:`read_postings` projects every folded event down to these and only these,
# so a consumer that iterates or re-serializes a row sees nothing it did not see
# before the format changed. Event metadata (``recorded``, ``source``, ``forget``)
# is reachable through :func:`fold` for callers that actually want it.
POSTING_KEYS = ("company", "slug", "date", "status", "role", "url")

# Provenance of an appended event. Kept as a documented tuple rather than an
# enum because the value is written into the file verbatim and read by humans.
# ``handoff`` is the creation-time append: job-search scaffolded the application
# folder, which is a strictly earlier moment than any status transition.
SOURCES = ("backfill", "handoff", "sync", "update")

_RECORDED_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
_WHITESPACE = re.compile(r"\s+")


def _collapse_ws(text: str) -> str:
    """Every run of whitespace (including a stray newline or tab) becomes one space."""
    return _WHITESPACE.sub(" ", text)


def _text(value) -> str:
    return "" if value is None else str(value)


def norm_url(u: str) -> str:
    """Normalize a URL for the fold identity: collapse ws, strip, casefold, drop a trailing ``/``.

    The query string and the fragment are KEPT. Dropping the query collapses the
    369-row starting corpus's 367 distinct URLs to 353 — an over-merge, and an
    over-merge in a skip-log means a posting that was never considered is treated
    as already handled and never surfaces again.
    """
    return _collapse_ws(_text(u)).strip().casefold().rstrip("/")


def norm_text(s: str) -> str:
    """Normalize a company or role for the fold identity: collapse ws, strip, casefold."""
    return _collapse_ws(_text(s)).strip().casefold()


def fold_key(row: dict) -> tuple:
    """The identity two lines share when they describe the same posting.

    URL when there is one, else the ``(company, role)`` pair. The ``else`` branch
    is load-bearing, not a fallback for tidiness: the rows with no URL sit at
    statuses (``rejected``, ``in_progress``) whose folders an owner is most likely
    to delete — exactly the rows this log exists to outlive. A URL-only identity
    would drop them.

    The two branches are tagged (``"url"`` / ``"pair"``) so they can never collide:
    a URL-bearing row and a URL-less row for the same company+role stay separate
    keys, which is what a reader would do too.

    Deduplication inside this file only — see the module docstring. Never a
    reader's match key.
    """
    url = norm_url(row.get("url"))
    if url:
        return ("url", url)
    return ("pair", norm_text(row.get("company")), norm_text(row.get("role")))


def _repair_torn_tail(path: Path) -> None:
    """Drop an unterminated trailing fragment so the next append cannot merge onto it.

    The only damage a single fsync'd ``O_APPEND`` write can leave is a final line
    with no terminator — a process that died mid-write. Appending behind it would
    glue the new event onto the fragment, turning a tolerable torn tail (which
    :func:`read_events` drops) into a malformed INTERIOR line, which raises: one
    crash would take the whole log offline. Nothing complete is lost here — an
    unterminated fragment is not a record, and :func:`read_events` was already
    ignoring it.
    """
    if not path.exists():
        return
    with open(path, "rb+") as fh:
        data = fh.read()
        if not data or data.endswith(b"\n"):
            return
        cut = data.rfind(b"\n")
        fh.truncate(cut + 1 if cut != -1 else 0)
        fh.flush()
        os.fsync(fh.fileno())


def read_events(path) -> list[dict]:
    """Every event in the file, parsed, in file order. Missing file -> ``[]``.

    An unterminated final line is a torn write and is dropped. Anything else that
    fails to parse — including a fully terminated final line — raises, because a
    single fsync'd append cannot produce a terminated-but-invalid line: such a
    line is real corruption, and silently skipping it silently loses a skip, which
    resurfaces a posting the owner already dealt with. Blank lines carry no event
    and are ignored.
    """
    path = Path(path)
    if not path.exists():
        return []
    raw = path.read_text(encoding="utf-8")
    if not raw:
        return []
    lines = raw.split("\n")
    # A complete file ends in "\n", so the split's final element is "". When it is
    # not, the last physical line was never terminated. Either way the final
    # element is not a record; drop it.
    lines = lines[:-1]
    events: list[dict] = []
    for number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"{path}: line {number} is not valid JSON — the skip-log is "
                f"corrupt and dropping the line would silently lose a skip; "
                f"recover the file from git history"
            ) from exc
        if not isinstance(event, dict):
            raise ValueError(
                f"{path}: line {number} is a {type(event).__name__}, not a JSON "
                f"object — every line must be one posting event"
            )
        events.append(event)
    return events


def fold(path) -> dict[tuple, dict]:
    """Collapse the event stream to the current state: ``fold_key -> last event``.

    File order, last wins — see the module docstring for why this must not sort on
    ``recorded``. An event carrying ``"forget": true`` removes its key from the
    result (the un-skip: a typo'd row is repaired by appending a tombstone, never
    by editing the file), and a later ordinary event for that same key brings it
    back.
    """
    state: dict[tuple, dict] = {}
    for event in read_events(path):
        key = fold_key(event)
        if event.get("forget"):
            state.pop(key, None)
        else:
            state[key] = event
    return state


def forgotten_keys(path) -> set:
    """Keys whose LAST event is a tombstone — the owner's explicit un-skips.

    :func:`fold` drops these, which makes "deliberately forgotten" and "never seen"
    indistinguishable in its output. Anything that RE-ADDS rows in bulk needs to tell
    the two apart, or it silently reverses a decision the owner made by hand. The
    concrete case: ``--backfill-log --force`` re-seeds from the retired YAML, which
    still contains every tombstoned row and is never updated, so a fresh generation
    would resurrect every un-skip ever performed.
    """
    forgotten = set()
    for event in read_events(path):
        key = fold_key(event)
        if event.get("forget"):
            forgotten.add(key)
        else:
            forgotten.discard(key)
    return forgotten


def _blank_if_none(value):
    return "" if value is None else value


def _posting(event: dict) -> dict:
    return {key: _blank_if_none(event.get(key)) for key in POSTING_KEYS}


def read_postings(path) -> list[dict]:
    """The folded skip-log as a list of rows shaped like the old YAML ``postings``.

    Every reader calls this and nothing else: each row carries exactly
    ``{company, slug, date, status, role, url}``, so the reader's existing
    normalizer, key construction, and registry expansion all keep working
    verbatim and its diff is a one-line change of where the list comes from. That
    is what makes the cutover behaviour-preserving by construction instead of by
    argument.
    """
    return [_posting(event) for event in fold(path).values()]


def append_event(path, row: dict, *, source: str, forget: bool = False,
                 recorded: str | None = None) -> None:
    """Append ONE event line for ``row``. The only write this module performs.

    ``source`` records who appended (``backfill`` / ``sync`` / ``update``).
    ``forget=True`` makes the line a tombstone that the fold honours; a row built
    by :func:`forget_row` already carries the flag. ``recorded`` defaults to now
    in UTC and is metadata only — nothing orders on it.

    Written as a single fsync'd ``O_APPEND`` write of one complete newline-
    terminated line, so the worst a crash can leave is a torn tail that the reader
    drops and the next append repairs. Parent directories are created.
    """
    path = Path(path)
    event = {key: "" for key in POSTING_KEYS}
    event.update({key: _blank_if_none(value) for key, value in dict(row).items()})
    event["recorded"] = recorded or datetime.now(timezone.utc).strftime(_RECORDED_FORMAT)
    event["source"] = str(source)
    if forget or event.get("forget"):
        event["forget"] = True
    else:
        event.pop("forget", None)

    line = json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n"
    # JSON escapes control characters inside strings, so this cannot trigger — it
    # is enforced rather than assumed because a raw newline inside a value would
    # split one event across two lines and hand the reader two malformed records.
    if "\n" in line[:-1]:
        raise ValueError(f"refusing to append a multi-line event to {path}")

    path.parent.mkdir(parents=True, exist_ok=True)
    _repair_torn_tail(path)
    data = line.encode("utf-8")
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    try:
        os.write(fd, data)
        os.fsync(fd)
    finally:
        os.close(fd)


def forget_row(url: str | None = None, company: str | None = None,
               role: str | None = None) -> dict:
    """Build a tombstone row that :func:`fold` drops, addressed by URL or company+role.

    The un-skip. Regeneration used to heal every wrong row for free; append-only
    removes that, so a typo'd company string would otherwise be immortal —
    suppressing every future posting that normalizes to it, with hand-editing an
    authoritative machine-owned file as the only remedy. Agents may not delete
    owner data, so the repair has to be an append.

    Requires enough to address a key: a URL, or both a company and a role.
    Anything less would tombstone ``("pair", "", "")`` — a key no real posting
    holds, so the un-skip would silently do nothing.
    """
    url = _text(url).strip()
    company = _text(company).strip()
    role = _text(role).strip()
    if not url and not (company and role):
        raise ValueError("forget_row needs a url, or both a company and a role")
    row = {key: "" for key in POSTING_KEYS}
    row.update({"url": url, "company": company, "role": role, "forget": True})
    return row


# --------------------------------------------------------------------------- #
# Applications -> posting rows -> appended events (the WRITER side)
#
# This is the sole producer of the row shape declared above, and it lives here,
# beside ``POSTING_KEYS``, because there is more than one writer. The tracker
# appends on every status transition and on ``--sync-log``; job-search's
# ``handoff.py`` appends the moment it scaffolds an application folder. Neither
# skill may import the other's ``scripts/``
# (``docs/handbook/skills-and-vendoring.md``), so the second writer's only other
# option was to hand-build rows out of its own field names — search JSON calls
# them ``title``/``company``/``url``, not ``role``/``slug``/``date``. That is
# precisely how two writers of one authoritative, never-rewritten file start
# disagreeing silently. One flattening, one append policy, vendored into both.
# --------------------------------------------------------------------------- #


def posting_row(row: dict) -> dict:
    """Project one flattened row onto exactly the keys this file stores.

    Two coercions, both load-bearing rather than cosmetic:

    * ``None`` becomes ``""`` because :func:`append_event` stores it that way.
      Comparing an unnormalized ``None`` against a stored ``""`` reads as a
      difference on EVERY run — one appended line per such posting per sync,
      forever. A ``meta.yaml`` carrying ``url:`` with no value produces exactly
      that.
    * A non-string scalar becomes its string form because an unquoted
      ``research_date:`` in ``meta.yaml`` loads as a ``datetime.date``, which
      ``json.dumps`` refuses outright — the append would crash instead of write.
      A YAML writer never hit this, because ``safe_dump`` serializes dates.
    """
    projected = {}
    for key in POSTING_KEYS:
        value = row.get(key)
        if value is None:
            projected[key] = ""
        else:
            projected[key] = value if isinstance(value, str) else str(value)
    return projected


def posting_rows(app: dict) -> list[dict]:
    """Flatten ONE application into its skip-log rows — one row per posting.

    ``app`` is the application-folder view both writers already hold:
    ``company`` / ``slug`` / ``date`` / ``status`` (the folder's derived rollup)
    plus a ``jobs`` list of per-posting dicts, or — for a pre-``jobs`` folder —
    the flat ``role`` / ``url`` pair.

    **Each posting keeps its OWN status**, falling back to the folder's rollup
    only when it has none: a rejected role at a company whose other role is still
    live must not inherit the live status. Listing every posting individually is
    also what lets a NEW role at an already-applied company surface — only the
    exact posting is skipped, never the employer.

    Rows come back already projected through :func:`posting_row`, so a caller can
    hand them straight to :func:`record_postings`.
    """
    common = {
        "company": app.get("company", ""),
        "slug": app.get("slug", ""),
        "date": app.get("date", ""),
    }
    folder_status = app.get("status", "")
    jobs = app.get("jobs")
    rows: list[dict] = []
    if isinstance(jobs, list) and jobs:
        for job in jobs:
            if not isinstance(job, dict):
                continue
            rows.append({**common,
                         "status": str(job.get("status") or "").strip()
                         or folder_status,
                         "role": job.get("role", ""),
                         "url": job.get("url", "")})
    else:
        rows.append({**common,
                     "status": folder_status,
                     "role": app.get("role", ""),
                     "url": app.get("url", "")})
    return [posting_row(row) for row in rows]


def record_postings(path, rows: list[dict], *, source: str) -> int:
    """Append the postings that differ from the folded log; return how many.

    The only write is an append, so **a key in the fold with no matching folder
    is left alone** — that is the entire point of the format. Deleting an
    application folder does not un-skip its posting.

    **Idempotent by comparison, not by lock.** A row identical to what the fold
    already holds appends nothing, so a writer may call this unconditionally —
    which is what both writers do, because "did anything change?" guards are how
    the FIRST event for a posting gets skipped.

    Two rows can share one identity key: a re-application carries the same URL
    under a new slug and a new date, and a multi-role folder can list one URL
    twice. The fold holds one event per key, so if both rows reached the loop at
    least one of them would differ from whatever the fold currently says and
    append — on every run, forever, with the fold's answer alternating between
    the two. Refreshing ``state[key]`` in the loop is not enough on its own (it
    makes BOTH rows append instead of one), so colliding rows are collapsed
    first, last-wins.

    ``state[key] = row`` still runs in the loop, and still matters: it keeps the
    fold consistent with what has already been written during this call, so the
    function stays correct for any caller that hands it rows it did not collapse.

    **Concurrency is the file format's, not this function's.** Two writers racing
    can both read the fold before either appends, and both then append; the
    result is two lines that fold to one, which is the tolerance an append-only
    log is built on. There is deliberately no lock here — a second writer holding
    a lock the first one does not is not mutual exclusion, and
    :func:`append_event`'s single fsync'd ``O_APPEND`` write is the whole
    interlock every appender shares.
    """
    by_key: dict[tuple, dict] = {}
    for raw in rows:
        row = posting_row(raw)
        by_key[fold_key(row)] = row

    state = fold(path)
    appended = 0
    for key, row in by_key.items():
        prev = state.get(key)
        if prev is None or any(prev.get(f) != row[f] for f in POSTING_KEYS):
            append_event(path, row, source=source)
            state[key] = row
            appended += 1
    return appended
