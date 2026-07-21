#!/usr/bin/env python3
"""Fetch a job-posting page and save its readable text VERBATIM.

Usage:
  .venv/bin/python .agents/skills/job-search/scripts/fetch_jd.py \
      <URL> --out <path> [--force] [--timeout SECS] [--digest]

Downloads the posting page over stdlib ``urllib`` (a descriptive User-Agent, a
timeout, HTTP redirects followed automatically) and extracts the human-readable
text with a small ``html.parser``-based reader: script / style / nav / header /
footer / form chrome is dropped, while heading / paragraph / list structure is
kept as plain markdown-ish text. The saved text is a FAITHFUL copy of the page's
readable content — there is NO summarization and NO rewriting anywhere in this
path, so a later agent reads the real posting instead of a lossy paraphrase.

Idempotent: if ``--out`` already exists it is kept untouched (pass ``--force`` to
overwrite). On success stdout is exactly the saved path + byte count. An HTTP
failure or an empty extraction exits non-zero with a clear stderr message; a
suspiciously tiny extraction still saves but warns that the page may be
JavaScript-rendered and suggests saving it manually.

``--digest`` additionally prints (after the saved path line, and whether the file
was freshly fetched or kept) a compact, deterministic LOCATOR over the saved JD:
it points a verifying agent at exactly the lines the hard gates read — title /
level, workplace / location, and visa / sponsorship — so a routine gate check
does not require reading the whole 10-26 KB file. The verbatim JD stays on disk
unchanged and is still required for handoff / drafting / honesty gates; the digest
is a locator, never a verdict (see ``build_digest``). Without ``--digest`` stdout
and every side effect are byte-identical to before.

The fetch / save path is stdlib only — no third-party dependencies, so it runs on
any ``python``. ``--digest`` alone reuses the skill's vendored gate classifiers
(``job_metadata`` / ``location`` under ``_vendor/``) so it locates EXACTLY the
signals the meta gates consume; that import happens lazily, only when ``--digest``
is passed, keeping the default path dependency-free.
"""
from __future__ import annotations

import argparse
import re
import sys
import urllib.error
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

# A descriptive User-Agent so ATS boards serve the full server-rendered page
# instead of a bot-blocked stub; kept generic (no identity) for the public repo.
USER_AGENT = "jobs-finder-skill/1.0 (job posting fetch; +https://github.com/)"

# Below this many extracted bytes we suspect a JavaScript-rendered shell and warn.
_TINY_EXTRACTION_BYTES = 500

# Chrome / non-content elements whose text is dropped wholesale.
_SKIP_TAGS = frozenset({
    "script", "style", "noscript", "template", "head", "title", "svg",
    "iframe", "nav", "header", "footer", "form",
})

# Headings open a line prefixed with the matching number of '#'.
_HEADINGS = {"h1": 1, "h2": 2, "h3": 3, "h4": 4, "h5": 5, "h6": 6}

# Block-level tags that end the current line and open a plain paragraph line.
_GENERIC_BLOCKS = frozenset({
    "p", "div", "section", "article", "main", "ul", "ol", "dl", "dt", "dd",
    "table", "thead", "tbody", "tfoot", "tr", "blockquote", "figure",
    "figcaption", "address", "details", "summary", "aside",
})

# Table cells stay on their row's line but get a separating space.
_CELL_TAGS = frozenset({"td", "th"})

_WS_RE = re.compile(r"\s+")
_MULTINL_RE = re.compile(r"\n{3,}")


class _ReadableTextExtractor(HTMLParser):
    """Collect readable text as ``(kind, line)`` blocks, dropping chrome elements.

    ``kind`` is one of ``heading`` / ``li`` / ``pre`` / ``para`` and only steers
    how blocks are spaced on render — the text itself is preserved verbatim
    (``convert_charrefs`` decodes entities; nothing is summarized or reworded).
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[tuple[str, str]] = []
        self._buf: list[str] = []
        self._kind = "para"
        self._prefix = ""
        self._skip = 0

    # -- line assembly ---------------------------------------------------- #
    def _flush(self) -> None:
        raw = "".join(self._buf)
        self._buf = []
        if self._kind == "pre":
            text = raw.strip("\n").rstrip()          # preserve interior newlines
        else:
            text = _WS_RE.sub(" ", raw).strip()      # collapse layout whitespace
        if text:
            self.blocks.append((self._kind, self._prefix + text))

    def _open_block(self, kind: str, prefix: str = "") -> None:
        self._flush()
        self._kind = kind
        self._prefix = prefix

    def _close_block(self) -> None:
        self._flush()
        self._kind = "para"
        self._prefix = ""

    # -- HTMLParser hooks ------------------------------------------------- #
    def handle_starttag(self, tag, attrs):
        if tag in _SKIP_TAGS:
            self._skip += 1
            return
        if self._skip:
            return
        if tag in _HEADINGS:
            self._open_block("heading", "#" * _HEADINGS[tag] + " ")
        elif tag == "li":
            self._open_block("li", "- ")
        elif tag == "pre":
            self._open_block("pre")
        elif tag == "br":
            self._flush()                            # line break, same kind
        elif tag in _CELL_TAGS:
            if self._buf:
                self._buf.append(" ")
        elif tag in _GENERIC_BLOCKS:
            self._open_block("para")

    def handle_startendtag(self, tag, attrs):
        if tag in _SKIP_TAGS or self._skip:
            return
        if tag in ("br", "hr"):
            self._flush()

    def handle_endtag(self, tag):
        if tag in _SKIP_TAGS:
            if self._skip:
                self._skip -= 1
            return
        if self._skip:
            return
        if tag in _HEADINGS or tag == "li" or tag == "pre" or tag in _GENERIC_BLOCKS:
            self._close_block()

    def handle_data(self, data):
        if self._skip:
            return
        self._buf.append(data)

    # -- result ----------------------------------------------------------- #
    def get_text(self) -> str:
        self._flush()
        out: list[str] = []
        prev_kind = None
        for kind, line in self.blocks:
            if out:
                # Consecutive list items stay tight; every other block boundary
                # gets a blank line, the way markdown separates paragraphs.
                out.append("\n" if kind == "li" and prev_kind == "li" else "\n\n")
            out.append(line)
            prev_kind = kind
        text = _MULTINL_RE.sub("\n\n", "".join(out)).strip()
        return text + "\n" if text else ""


class FetchError(RuntimeError):
    """A network / HTTP failure while downloading the posting page."""


def extract_readable_text(html_text: str) -> str:
    """Return the page's readable text as plain markdown-ish blocks (verbatim)."""
    parser = _ReadableTextExtractor()
    parser.feed(html_text)
    parser.close()
    return parser.get_text()


# --------------------------------------------------------------------------- #
# Digest (--digest): a compact, deterministic LOCATOR over the saved JD.
#
# The verbatim JD stays on disk unchanged; the digest points a verifying agent at
# exactly the lines the hard gates read — title/level, workplace/location, and
# visa/sponsorship — so a routine gate check does not require re-reading the whole
# 10-26 KB file. It is a locator, never a verdict: it reuses the SAME vendored
# classifiers the meta gates consume (``job_metadata.classify_level`` and its
# ``_SPONSOR_*`` phrase lists; ``location.extract_jd_locations``) to FIND the
# gate-relevant lines and prints them VERBATIM for the agent to judge — the script
# locates, the agent decides. Anything ambiguous or missing -> open the full file.
# --------------------------------------------------------------------------- #

_DIGEST_HEADER = (
    "--- JD DIGEST (deterministic locator over the saved JD; verify the hard "
    "gates from these lines, open the full JD for anything ambiguous) ---"
)
_DIGEST_LINE_WIDTH = 160         # per printed JD line (workplace/location context)
_DIGEST_SENTENCE_WIDTH = 400     # per printed visa/sponsorship sentence
_DIGEST_MAX_WORKPLACE_LINES = 40  # cap; overflow points to the full JD
_DIGEST_MAX_VISA_SENTENCES = 20   # cap; overflow points to the full JD

# Workplace / location signal keywords (the LESSONS gate: never trust the scraper
# ``remote`` flag — read the JD's own words). ``reloc\w*`` catches relocate/
# relocation; ``on[- ]?site`` catches onsite / on-site / on site. "distributed" is
# deliberately excluded (location.py rejects it as an unreliable remote signal — it
# false-matches "distributed systems"); "office" already covers "in-office".
_WORKPLACE_KW_RE = re.compile(
    r"\b(remote|hybrid|on[- ]?site|in[- ]?office|in[- ]?person|work from home|"
    r"wfh|work remotely|reloc\w*|office|anywhere)\b",
    re.I,
)
# Visa / sponsorship keyword stems — a SUPERSET of the distinctive stems in
# ``job_metadata``'s ``_SPONSOR_NEGATIVE`` / ``_SPONSOR_POSITIVE`` phrase lists, so
# a sentence carrying any sponsorship signal is located even for wordings the exact
# phrase lists do not enumerate. The phrase lists themselves are ALSO matched
# (below) so list-only phrasings like "gc only" / "perm process" are never missed.
_VISA_KW_RE = re.compile(
    r"(sponsor\w*|visa|h-?1b|green[- ]card|work authoriz\w*|authoriz\w* to work|"
    r"citizen\w*|immigration|permanent resident\w*|cap[- ]exempt|perm process)",
    re.I,
)
# Split a line into sentences on terminal punctuation (kept with the sentence).
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")

# Equal-opportunity boilerplate lists "citizenship" as a PROTECTED CLASS, not a
# sponsorship requirement — it appears in nearly every US JD and would otherwise
# dominate the visa section. A sentence hitting one of these EEO markers with NO
# strong sponsorship term is dropped from the visa locator (a real denial like "US
# citizens only" carries no EEO marker, so it is kept).
_EEO_MARKER_RE = re.compile(
    r"without regard to|protected by law|equal opportunity|equal employment|"
    r"regardless of (?:race|sex|gender|age)|national origin", re.I)
_STRONG_VISA_RE = re.compile(
    r"sponsor|visa|h-?1b|green[- ]card|work authoriz|permanent resident|"
    r"cap[- ]exempt|perm process", re.I)

# A "Location(s)" / "Available Locations" section heading — ATS pages (Greenhouse,
# Ashby) list the true location as a bullet block UNDER such a heading, with NO
# colon, so location.extract_jd_locations (colon-anchored) never sees it. Matching
# the heading lets the digest pull the location bullets that follow. The word
# boundary keeps "Relocation" from matching.
_LOC_HEADING_RE = re.compile(
    r"^\s*#{0,6}\s*\**\s*(?:available\s+|primary\s+|work\s+|office\s+)?locations?\b",
    re.I,
)
# Common ATS nav chrome the reader leaves above the real <h1> title; skipped so the
# digest titles the posting, not a breadcrumb.
_NAV_CHROME = frozenset({
    "back to jobs", "back", "apply", "apply now", "apply for this job",
    "share", "share this job", "view all jobs", "all jobs", "see all jobs",
    "menu", "home", "careers", "job details",
})
# A non-verbatim provenance note (the reference.md JD-fetch fallback convention:
# scraper-extracted text saved WITH a leading "> NOTE: non-verbatim — ..." header)
# leads some saved JDs. Its marker is recognized so the header block is skipped and
# the title comes from the real posting body, not the provenance note.
_PROVENANCE_MARKER_RE = re.compile(r"non[- ]?verbatim", re.I)


def _load_digest_helpers():
    """Lazily import the vendored gate classifiers the digest reuses.

    Kept out of the module top level so the fetch/save path stays stdlib-only and
    byte-identical without ``--digest``. Puts this skill's ``scripts/`` + ``_vendor/``
    on ``sys.path`` (exactly as ``handoff.py`` does) and returns the reused symbols.
    """
    scripts_dir = Path(__file__).resolve().parent
    vendor = scripts_dir / "_vendor"
    for candidate in (str(scripts_dir), str(vendor)):
        if candidate not in sys.path:
            sys.path.insert(0, candidate)
    from job_metadata import (  # noqa: E402  (vendored gate classifiers)
        classify_level,
        _SPONSOR_NEGATIVE,
        _SPONSOR_POSITIVE,
        _source_text,
    )
    from location import (  # noqa: E402  (vendored location policy helpers)
        extract_jd_locations,
        _JD_LOC_RE,
        _FOREIGN_TOKENS,
        FOREIGN_REGIONS,
        _FOREIGN_ABBR_RE,
    )
    # Foreign is the decisive NO-MATCH location signal and is often stated only in
    # prose / a title / an "Available Locations" bullet, so reuse location.py's OWN
    # foreign place names — but match them on WORD BOUNDARIES here. location.py
    # substring-matches these against short location strings; over full JD prose a
    # substring match false-fires ("apac" in "capacity", "india" in "Indiana",
    # "paris" in "comparison"), so the digest anchors them as whole words. Short/
    # punctuated abbreviations (uk / eu) stay with location's own _FOREIGN_ABBR_RE.
    foreign_words = sorted(
        {t.strip() for t in (_FOREIGN_TOKENS + FOREIGN_REGIONS)
         if re.fullmatch(r"[a-z][a-z ]{2,}", t.strip())},
        key=len, reverse=True,
    )
    foreign_re = re.compile(
        r"\b(" + "|".join(re.escape(w) for w in foreign_words) + r")\b", re.I)
    return {
        "classify_level": classify_level,
        "sponsor_phrases": tuple(_SPONSOR_NEGATIVE) + tuple(_SPONSOR_POSITIVE),
        "unescape": _source_text,
        "extract_jd_locations": extract_jd_locations,
        "jd_loc_re": _JD_LOC_RE,
        "foreign_re": foreign_re,
        "foreign_abbr_re": _FOREIGN_ABBR_RE,
    }


def _clip(text: str, width: int) -> str:
    text = text.strip()
    return text if len(text) <= width else text[: width - 1].rstrip() + "…"


def _skip_provenance_header(lines: list[str]) -> list[str]:
    """Drop a leading non-verbatim provenance header (reference.md fallback convention).

    Returns the lines AFTER a leading run of blockquote / marker lines when that run
    carries the ``non-verbatim`` marker, so the title heuristic titles the posting
    rather than the provenance note. Blank lines do not end the run; the first real
    content line does. A normal JD (no such marker) is returned unchanged.
    """
    last_header = -1
    has_marker = False
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue                       # blank lines do not end the header
        marker = bool(_PROVENANCE_MARKER_RE.search(stripped))
        if stripped.startswith(">") or marker:
            last_header = i
            has_marker = has_marker or marker
            continue
        break                              # first real content line ends the scan
    return lines[last_header + 1:] if (has_marker and last_header >= 0) else lines


def _digest_title(lines: list[str]) -> str:
    """The posting title: the first H1, else the first non-chrome non-empty line.

    A leading non-verbatim provenance header (reference.md fallback convention) is
    skipped first; scraped ATS pages also frequently lead with nav chrome ("Back to
    jobs", "Apply") before the real ``# <title>`` H1, so an H1 (when present) is the
    reliable title and the fallback skips chrome / blockquote lines.
    """
    lines = _skip_provenance_header(lines)
    for line in lines:
        heading = re.match(r"^#\s+(.*\S)\s*$", line)   # H1 only ('# ', not '## ')
        if heading:
            return heading.group(1).strip()
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith(">"):   # a title is never a blockquote
            continue
        marked = re.match(r"^#{1,6}\s+(.*)$", stripped)
        text = (marked.group(1).strip() if marked else stripped)
        if text.lower() not in _NAV_CHROME:
            return text
    return ""


def _location_heading_block(lines: list[str], start: int) -> list[int]:
    """Indices of a ``Location(s)`` heading plus the location lines beneath it.

    Walks forward from the heading, skipping a single blank gap, collecting the
    bullet/short lines that name the location(s), and stopping at the next heading
    or the blank line that follows the block. Bounded so a mislabeled heading cannot
    drag in the whole body.
    """
    picked = [start]
    seen_content = False
    for j in range(start + 1, min(len(lines), start + 8)):
        stripped = lines[j].strip()
        if not stripped:
            if seen_content:
                break
            continue
        if re.match(r"^#{1,6}\s+", stripped):
            break
        picked.append(j)
        seen_content = True
    return picked


def _workplace_signal_lines(lines, helpers) -> tuple[list[str], bool]:
    """Every workplace/location signal line (±1 line of context), deduped.

    Interesting lines are the union of: ``Location:`` label lines (location's own
    ``_JD_LOC_RE``); lines matching a workplace keyword; a ``Location(s)`` /
    ``Available Locations`` heading and the location bullets beneath it (the ATS
    pattern colon-anchored parsing misses); and lines naming a FOREIGN place (reused
    from location.py — the decisive no-match signal, often prose/title/bullet only).
    Each is shown with ±1 line of context and marked ``>``; blank context lines are
    dropped and a gap between blocks prints a ``…`` separator. Returns
    (rendered_lines, truncated).
    """
    jd_loc_re = helpers["jd_loc_re"]
    unescape = helpers["unescape"]
    foreign_re = helpers["foreign_re"]
    foreign_abbr_re = helpers["foreign_abbr_re"]
    match_idxs = {i for i, ln in enumerate(lines) if jd_loc_re.match(ln)}
    for i, ln in enumerate(lines):
        norm = re.sub(r"\s+", " ", unescape(ln)).lower()
        if (_WORKPLACE_KW_RE.search(norm)
                or foreign_abbr_re.search(norm)
                or foreign_re.search(norm)):
            match_idxs.add(i)
        if _LOC_HEADING_RE.match(ln):
            match_idxs.update(_location_heading_block(lines, i))
    context: set[int] = set()
    for i in match_idxs:
        for j in (i - 1, i, i + 1):
            if 0 <= j < len(lines):
                context.add(j)

    rendered: list[str] = []
    truncated = False
    prev = None
    for j in sorted(context):
        raw = lines[j].strip()
        if not raw and j not in match_idxs:
            continue
        if len(rendered) >= _DIGEST_MAX_WORKPLACE_LINES:
            truncated = True
            break
        if prev is not None and j - prev > 1:
            rendered.append("       …")
        marker = ">" if j in match_idxs else " "
        rendered.append(f"{marker} L{j + 1:>4} | {_clip(raw, _DIGEST_LINE_WIDTH)}")
        prev = j
    return rendered, truncated


def _visa_sentences(lines, helpers) -> tuple[list[str], bool]:
    """Every visa/sponsorship sentence, located (not classified), deduped.

    A line is a candidate when it carries a visa keyword OR a phrase from the reused
    ``classify_sponsorship`` phrase lists; within it, only the matching sentence(s)
    are kept so a long paragraph does not drag its whole body in. Verbatim, no
    verdict — the agent judges offer vs denial. Returns (sentences, truncated).
    """
    phrases = helpers["sponsor_phrases"]
    unescape = helpers["unescape"]

    def _is_signal(norm: str) -> bool:
        return bool(_VISA_KW_RE.search(norm)) or any(p in norm for p in phrases)

    found: list[str] = []
    seen: set[str] = set()
    truncated = False
    for line in lines:
        text = unescape(line)
        if not _is_signal(re.sub(r"\s+", " ", text).strip().lower()):
            continue
        for sentence in _SENTENCE_SPLIT_RE.split(text):
            clean = sentence.strip().lstrip("#-*•> ").strip()
            norm = re.sub(r"\s+", " ", clean).strip().lower()
            if not norm or not _is_signal(norm) or norm in seen:
                continue
            # Drop equal-opportunity boilerplate: "citizenship" as a protected class,
            # not a sponsorship requirement (kept only if a real sponsorship term is
            # also present, which EEO text never carries).
            if _EEO_MARKER_RE.search(norm) and not _STRONG_VISA_RE.search(norm):
                seen.add(norm)
                continue
            if len(found) >= _DIGEST_MAX_VISA_SENTENCES:
                truncated = True
                break
            seen.add(norm)
            found.append(_clip(clean, _DIGEST_SENTENCE_WIDTH))
        if truncated:
            break
    return found, truncated


def build_digest(text: str, *, jd_path: str, byte_count: int, helpers=None) -> str:
    """Build the deterministic ``--digest`` locator for one saved JD.

    ``text`` is the verbatim saved JD; ``jd_path`` / ``byte_count`` describe the
    file on disk (echoed in the tail escape-hatch line). ``helpers`` is the reused
    vendored-classifier bundle from ``_load_digest_helpers`` (loaded on demand when
    ``None``, so this is directly unit-testable). Output sections:

      (a) title + ``job_metadata.classify_level`` level/seniority read;
      (b) parsed ``Location:`` value(s) + every workplace/location signal line
          (±1 context), the LESSON that the scraper ``remote`` flag is untrusted;
      (c) every visa/sponsorship sentence located via the reused phrase lists +
          keyword stems (printed, never classified);
      (d) a tail line: full JD path + byte count + the LOCATOR/escape-hatch note.
    """
    helpers = helpers or _load_digest_helpers()
    lines = text.splitlines()

    # (a) title + level/seniority ----------------------------------------- #
    title = _digest_title(lines) or "(none extracted)"
    level, signal = helpers["classify_level"](title)
    level_line = f"LEVEL (job_metadata.classify_level on title): {level}"
    if level != "unknown" and signal:
        level_line += f'  [signal: "{_clip(signal, 60)}"]'

    # (b) workplace / location -------------------------------------------- #
    parsed = helpers["extract_jd_locations"](text)
    parsed_line = (
        "PARSED LOCATION(S) (location.extract_jd_locations): " + " | ".join(parsed)
        if parsed else
        'PARSED LOCATION(S): (none on a "Location:" line — read the signal lines below)'
    )
    workplace_lines, wp_truncated = _workplace_signal_lines(lines, helpers)

    # (c) visa / sponsorship ---------------------------------------------- #
    visa_lines, visa_truncated = _visa_sentences(lines, helpers)

    # ---- assemble -------------------------------------------------------- #
    out: list[str] = [_DIGEST_HEADER, ""]
    out.append(f"TITLE: {_clip(title, _DIGEST_LINE_WIDTH)}")
    out.append(level_line)
    out.append("")
    out.append(parsed_line)
    out.append(
        "WORKPLACE/LOCATION SIGNAL LINES (±1 line context; L# = line in the saved "
        "JD; '>' = signal line). Never trust a scraper 'remote' flag — judge from "
        "these words:"
    )
    if workplace_lines:
        out.extend(workplace_lines)
        if wp_truncated:
            out.append(
                f"  … more than {_DIGEST_MAX_WORKPLACE_LINES} signal lines — open the "
                "full JD for the rest.")
    else:
        out.append("  (no workplace/location keyword or 'Location:' line found)")
    out.append("")
    out.append(
        "VISA/SPONSORSHIP SENTENCES (located via classify_sponsorship phrase lists "
        "+ visa keywords — VERBATIM, NOT a verdict; you judge offer vs denial):"
    )
    if visa_lines:
        out.extend(f"  • {s}" for s in visa_lines)
        if visa_truncated:
            out.append(
                f"  … more than {_DIGEST_MAX_VISA_SENTENCES} sentences — open the "
                "full JD for the rest.")
    else:
        out.append("  (no visa/sponsorship sentence found — sponsorship is 'unknown' "
                   "from text; confirm with the employer)")
    out.append("")
    out.append(f"JD (verbatim, full): {jd_path} — {byte_count} bytes.")
    out.append(
        "NOTE: this digest only LOCATES gate-relevant lines; it is not a verdict and "
        "may omit nuance. If any workplace / visa / location / title signal is "
        "ambiguous or missing here, open the JD above and read it verbatim before "
        "deciding. The verbatim JD is still required for handoff, drafting, and the "
        "honesty gates."
    )
    return "\n".join(out)


def fetch_page(url: str, timeout: float) -> str:
    """GET ``url`` (following redirects) and return the decoded body.

    Raises ``FetchError`` with a human-readable message on any HTTP/network
    failure so the CLI can report it and exit non-zero.
    """
    req = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            charset = resp.headers.get_content_charset() or "utf-8"
    except urllib.error.HTTPError as exc:
        raise FetchError(f"HTTP {exc.code} {exc.reason} for {url}") from exc
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        reason = getattr(exc, "reason", exc)
        raise FetchError(f"could not fetch {url}: {reason}") from exc
    return raw.decode(charset, "replace")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Fetch a job-posting page and save its readable text verbatim.")
    ap.add_argument("url", help="URL of the job-posting page to fetch.")
    ap.add_argument("--out", required=True,
                    help="File path to write the extracted text to "
                         "(parent directories are created).")
    ap.add_argument("--force", action="store_true",
                    help="Overwrite --out if it already exists "
                         "(default: keep the existing file and report it).")
    ap.add_argument("--timeout", type=float, default=25.0,
                    help="Network timeout in seconds (default: %(default)s).")
    ap.add_argument("--digest", action="store_true",
                    help="Also print a compact, deterministic LOCATOR over the saved "
                         "JD (title/level, workplace/location, visa/sponsorship "
                         "signal lines) so gate verification does not require reading "
                         "the whole file. The verbatim JD is saved unchanged either "
                         "way; without --digest stdout is byte-identical to before.")
    args = ap.parse_args(argv)

    out_path = Path(args.out).expanduser()

    # Idempotent: an existing file is authoritative — keep it, no fetch. With
    # --digest, still emit the digest from the file already on disk (the common
    # flow: handoff.py saved the JD, now verify its gates without re-fetching).
    if out_path.exists() and not args.force:
        n = out_path.stat().st_size
        print(f"{out_path} ({n} bytes) [kept existing]")
        if args.digest:
            _emit_digest(out_path.read_text(encoding="utf-8", errors="replace"),
                         out_path, n)
        return 0

    try:
        html_text = fetch_page(args.url, args.timeout)
    except FetchError as exc:
        print(f"fetch_jd: {exc}", file=sys.stderr)
        return 1

    text = extract_readable_text(html_text)

    if not text.strip():
        print(f"fetch_jd: no readable text extracted from {args.url} — the page is "
              f"likely JavaScript-rendered; open it in a browser and save the "
              f"posting text manually.", file=sys.stderr)
        return 1

    data = text.encode("utf-8")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(data)
    n = len(data)
    print(f"{out_path} ({n} bytes)")

    if n < _TINY_EXTRACTION_BYTES:
        print(f"fetch_jd: warning — only {n} bytes extracted "
              f"(< {_TINY_EXTRACTION_BYTES}); the page may be JavaScript-rendered. "
              f"Review {out_path}; if it is incomplete, save the posting text "
              f"manually.", file=sys.stderr)

    if args.digest:
        _emit_digest(text, out_path, n)
    return 0


def _emit_digest(text: str, out_path: Path, byte_count: int) -> None:
    """Print the digest to stdout; never let a digest error break the save contract.

    The verbatim JD is already saved (or kept) and its status line already printed;
    the digest is a best-effort add-on, so any failure building it degrades to a
    one-line stderr note pointing at the full file rather than a non-zero exit.
    """
    try:
        print()
        print(build_digest(text, jd_path=str(out_path), byte_count=byte_count))
    except Exception as exc:  # noqa: BLE001 — digest must never break the save
        print(f"fetch_jd: could not build --digest ({exc}); read the full JD at "
              f"{out_path}.", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
