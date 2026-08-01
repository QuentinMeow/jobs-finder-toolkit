# A residency place written "the U.S." is truncated to "the U" and stays at review

- **Priority**: P2 (someday)
- **Area**: job-search
- **Source**: found by the frozen verdict matrix while fixing the US-country
  residency regression (branch `fix/45-us-remote-residency`, 2026-08-01). Pinned
  by `test_a_dotted_abbreviation_stays_at_review_on_purpose` so it is a recorded
  decision rather than a surprise.
- **Claimed-by**:

## Goal

Let `automation/shared/location.py` read a residency clause whose place is written
with the dotted abbreviation (`you must reside in the U.S.`) without letting a
residency clause run past its own sentence.

## Context

`_JD_RESIDENCY_RE`'s place group is `[^.;:!?\n]{2,60}` — the excluded `.` is what
stops a clause from swallowing the sentences after it. The same exclusion
truncates a dotted abbreviation:

```
"You must reside in the United States."  -> place = "United States"   (read)
"Candidates must be located in the US."  -> place = "US"              (read)
"You must reside in the U.S."            -> place = "the U"           (unreadable)
```

So the dotted form falls to `residency_restriction_unparsed` and the posting goes
to manual review. That is the safe direction — noise, never a lost posting — but
`U.S.` is common boilerplate, so it is real noise.

**The obvious fix is wrong and this is the reason to write the task down.**
Widening the place class to admit dots would ALSO widen it for
`"You must reside in the U.S. or Canada."`, which truncates identically to
`"the U"`. A dotted reading would call that posting US-remote, while the
spelled-out `"the United States or Canada"` correctly stays `foreign` / `no_match`
because the whole phrase reaches the foreign check. That is a
no_match -> match move on a foreign-scoped role: the one direction this module
must never move in.

Any fix therefore has to keep the sentence boundary while distinguishing an
abbreviation's internal dots from a full stop. A sentence-boundary regex
(`\.(?=\s+[A-Z])` or `\.\s*$`) rather than a bare `.` is the shape to try, and it
must be validated against the multi-country phrasing above, not only the happy
path.

Do not attempt this without a before/after verdict matrix: the residency reader
serves the metro, state, hub, foreign and country readings from ONE capture, so a
change to the capture moves all five at once.

## Definition of done

- `you must reside in the U.S.` / `in the U.S.A.` classify as `match` /
  `us_remote` with `jd_residency_us_scope`.
- `you must reside in the U.S. or Canada` still classifies `no_match` / `foreign`.
- A residency clause still cannot capture text from the following sentence — a
  test with a foreign city named in the NEXT sentence keeps its US verdict.
- `test_a_dotted_abbreviation_stays_at_review_on_purpose` in
  `automation/shared/tests/test_location.py` is replaced by the positive cases
  above (it exists only to pin the current residual).
- `automation/shared/tests`, `skills/job-search/scripts/tests` and
  `validate_filter_variants.py --check` all pass; vendored copies re-synced.
