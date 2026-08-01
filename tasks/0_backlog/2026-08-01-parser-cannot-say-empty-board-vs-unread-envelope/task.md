# `parse_manifest` cannot say whether a board was empty or its envelope went unread

- **Priority**: P2 (someday)
- **Area**: job-search
- **Source**: adversarial audit #4 finding 10; the count and the stderr line
  shipped, the discrimination did not
- **Claimed-by**: <(set when work starts, before the first change)>

## Goal

A build that reads a present payload and gets no rows says WHICH of the two it
was: the board genuinely has no open postings, or the parser no longer matches the
payload it was handed.

## Context

`posting_parsers.parse_manifest` returns `list[dict]` and nothing else, so
`build_postings._collect` can only observe "zero rows". It now counts those
manifests and prints one stderr line per build naming the sources
(`_report_collect_notes`), which is what makes a source-wide parser regression
visible at all — but the line has to hedge ("an empty board, or a parser that no
longer matches the payload"), and on a store with several employers who have no
open roles it will fire every build.

The discriminator exists in the payload: every parser reaches its rows through a
known list path (`data["jobs"]`, `data["jobPostings"]`, …). A key that is present
and empty is an empty board; a key that is absent is an envelope the parser did
not recognize. `automation/search-recall-audit/field_fidelity.py` already keeps
that map as `_RAW_LOCATORS` for all eleven sources, so the shape is proven — but
it lives outside the skill and would drift if simply copied. The fix is to give
`posting_parsers` the list paths as its own single source of truth and have
`field_fidelity` read them from there.

## Definition of done

- [ ] `posting_parsers` exposes the per-source list path and a way to ask
      "recognized envelope, zero rows" vs "unrecognized envelope"
- [ ] `_collect` counts only the unrecognized case; an empty board is silent
- [ ] `field_fidelity._RAW_LOCATORS` reads the list paths from `posting_parsers`
      rather than restating them
- [ ] Tests: an empty board prints nothing; a changed envelope is counted and
      named; both against all eleven sources' real payload shapes
