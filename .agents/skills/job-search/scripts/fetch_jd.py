#!/usr/bin/env python3
"""Fetch a job-posting page and save its readable text VERBATIM.

Usage:
  .venv/bin/python .agents/skills/job-search/scripts/fetch_jd.py \
      <URL> --out <path> [--force] [--timeout SECS]

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

Stdlib only — no third-party dependencies, so it runs on any ``python`` and needs
nothing vendored from the toolkit.
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
    args = ap.parse_args(argv)

    out_path = Path(args.out).expanduser()

    # Idempotent: an existing file is authoritative — keep it, no fetch.
    if out_path.exists() and not args.force:
        n = out_path.stat().st_size
        print(f"{out_path} ({n} bytes) [kept existing]")
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
