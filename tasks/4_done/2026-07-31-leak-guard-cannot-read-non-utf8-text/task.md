# The leak guard counts a non-UTF-8 text file instead of scanning it

- **Priority**: P2 (someday)
- **Area**: repo
- **Source**: filed by the implementing session of
  `2026-07-31-leak-guard-silently-skips-an-unreadable-file`, 2026-07-31 — the one
  path that task's Definition of done explicitly told it not to change
- **Claimed-by**: implementing agent, 2026-08-02

## Goal

Decide whether a tracked text file that is not valid UTF-8 should be decoded with a
fallback and scanned, or should stay counted-but-unscanned — and make the guard do
whichever is chosen, deliberately.

## Context

`automation/publish/check_public.py` now separates *opened but no text to scan* from
*never opened*, fails closed on the second, and prints a `not inspected:` line with a
per-reason breakdown. A non-UTF-8, NUL-free file (a latin-1 `.md`, say) lands in the
first bucket: the guard opens it, cannot decode it, counts it, and passes.

That is a real remaining hole, and the narrowest one left: a personal name sitting in
a latin-1 text file is not seen by the token scan. It is now *visible* — the count and
the `--json` output both name it — where before it was invisible, which is why the
implementing session left it rather than widening its own change.

The decision is not obvious, which is why this is a task and not a bug:

- Decoding with `errors="replace"` or a latin-1 fallback scans the bytes, but a
  replacement character can split a token and defeat the substring match anyway, so
  the added coverage may be smaller than it looks. Measure before assuming.
- Failing closed on undecodable text would be the strictest reading, but the tree may
  legitimately carry such a file; check whether it does before proposing it.

Weigh it against how a real leak would actually arrive. Every tracked text file this
repo writes is UTF-8, so the realistic path is a file pasted in from elsewhere.

## Decision (2026-08-02): decode and scan

**DECODE-AND-SCAN**, with a decoder that is neither of the two the task warned about.

Measurement first, as the task asked. A full export dry-run on the tree at `f360aec`
reported `not inspected: 7 (binary-sniff: 3, extract-failed: 1, guard-self: 1,
no-text-extractor: 2)` — **zero** `not-utf8` files tracked today. So the change
cannot destabilize anything currently in the tree, and fail-closed would have been a
gate armed against a case that never happens while still red-lighting the first
legitimate latin-1 fixture anyone adds.

The task's objection to decode-and-scan was correct about both single-codec options,
and both were measured rather than assumed:

- `errors="replace"` turns each rejected byte into U+FFFD, which SPLITS a
  latin-1-encoded token (`Bj\xf8rnholm` -> `Bj?rnholm`) — the substring match dies.
- Whole-file `latin-1` never fails but mojibakes every UTF-8-encoded non-ASCII token
  (`Z\xc3\xbcrich` -> `ZÃ¼rich`) — that match dies instead.

`_decode_lossless` splices them: valid UTF-8 sequences decode to their real
characters, and only the bytes UTF-8 rejects become their latin-1 characters (a 1:1
map over 0x00-0xFF). No byte is dropped, no token is split, and line numbers stay
true to the file because the decode is byte-preserving. Both failure modes above are
pinned by their own test, since each single codec passes the other one's case.

The NUL sniff still runs first, so compressed payloads are skipped rather than
decoded into megabytes of noise for the scanner.

Rejected: **fail-closed** (a strictly worse outcome than scanning bytes that can be
scanned — it certifies nothing where decoding certifies something, and it punishes a
legitimate fixture); **leave as is** (the whole point was that a name in a latin-1
note is still a name).

## Definition of done

- [x] A decision recorded: decode-and-scan, above and in the PR body.
- [x] Decode-and-scan: `NonUtf8TextScanTests` plants latin-1 files containing an
      identity token and asserts the guard finds them — ASCII token, latin-1-encoded
      non-ASCII token, and a UTF-8 token beside a stray latin-1 byte.
- [x] The `not inspected:` breakdown loses that reason — `SKIP_NOT_UTF8` is deleted,
      and such a file is counted in `content read:` with a `mixed encoding:` line
      naming it.
