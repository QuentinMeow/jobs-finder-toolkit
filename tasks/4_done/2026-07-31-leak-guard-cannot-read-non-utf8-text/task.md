# The leak guard counts a non-UTF-8 text file instead of scanning it

- **Priority**: P2 (someday)
- **Area**: repo
- **Source**: filed by the implementing session of
  `2026-07-31-leak-guard-silently-skips-an-unreadable-file`, 2026-07-31 — the one
  path that task's Definition of done explicitly told it not to change
- **Claimed-by**:

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

## Definition of done

- [ ] A decision recorded (in the PR body or `memory/decisions/` if it sets policy):
      decode-and-scan, fail-closed, or deliberately leave counted — with the reason.
- [ ] If decode-and-scan: a test plants a latin-1 file containing an identity token and
      asserts the guard finds it; the `not inspected:` breakdown loses that reason.
- [ ] If fail-closed: a test asserts the exit code and message, and the whole tree still
      passes.
- [ ] If left as is: one line in `check_public.py` naming this as a known, accepted gap,
      so the next auditor does not re-file it.
