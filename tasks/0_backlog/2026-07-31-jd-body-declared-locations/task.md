# Resolve geography from a declared locations line in the JD body

- **Priority**: P2 (someday)
- **Area**: job-search
- **Source**: branch `wip/17-location-gate-jd-body` — the fix for the live
  single-company location-gate false positive/negative deliberately stopped short
  of this. See that PR's Design section.

## Goal

Turn the `review` verdict that a workplace-word-only ATS location field now
produces into a confident `match`/`no_match` when — and only when — the JD body
carries an explicit, labelled locations declaration ("Available Locations: …",
"Office Locations: …"), so a board that hides its cities in the description does
not force a human to read every posting.

## Context

`automation/shared/location.py::assess_location` takes the full JD text and uses
it for the WORKPLACE decision (remote / hybrid / onsite JD rules) but never for
GEOGRAPHY: `foreign`, `us`, `preferred` and `has_specific_us_office` read the ATS
location field (plus, for foreign only, the title). Some boards put a workplace
word — `Hybrid`, `In-Office`, `Distributed` — in the location field and list the
real cities on an `Available Locations:` line inside every description. For those,
the gate has no geography at all and honestly answers `review`
(`workplace_tag_without_geography`).

Why it was not fixed in that PR:

- The obvious implementation — a line-anchored regex over the description — is not
  safe as written. `common.strip_html` replaces HTML tags with a SPACE, not a
  newline, so a description whose source HTML has no literal newlines collapses to
  one long line. A `^…$`-bounded capture then either misses the line entirely or
  swallows the following prose, and that prose routinely names other offices.
- The failure direction is the bad one. Every other change in that PR moves a
  verdict toward `review` (surface it) and at worst costs manual reading. A
  prose-derived city list can produce a confident `no_match` — a real match
  hidden, with nothing in the output to hint that a human should look.
- Volume did not justify the risk: a workplace-word location field already
  produced `review` before the change, so this is not a new backlog of postings.

Design sketch if picked up:

- A NEW extractor (do not widen `extract_jd_locations`, which serves JD files the
  pipeline itself writes and is deliberately strict). Match a labelled declaration
  from a small prefix allowlist (`available`, `office(s)`, `job`, `role`,
  `position`, `primary`, `work`, `posting`, `hiring`, `eligible`) immediately
  before `location(s):`.
- Bound the captured value against the collapsed-HTML case: cap the length and cut
  at a sentence boundary, then verify on recorded board fixtures that the capture
  is the city list and nothing after it.
- Feed the result into the positive-geography context (`us`, `preferred`,
  `has_specific_us_office`) and into foreign detection, tagged with its own
  evidence id so an operator can see the geography came from the body.
- Keep `hint_trusted`-style asymmetry in mind: consider letting the body list
  REJECT (`other_us` / `foreign`) only once it has been shown accurate on
  fixtures, and grant a match from it more cautiously.

## Definition of done

- Recorded board fixtures (fictional company/board, several real HTML shapes
  including one with no literal newlines) live beside the job-search tests; no
  live ATS fetch in any test.
- `assess_location` returns `no_match` for a workplace-word location field whose
  JD declares only non-preferred US cities, and `match` when the declared list
  contains a preferred metro — with the body-derived evidence id present.
- A fixture proves the extractor does NOT capture prose that follows the declared
  list on a collapsed single-line description.
- `automation/shared/tests`, `skills/job-search/scripts/tests` and
  `validate_filter_variants.py --check` all pass; new corpus cases added for the
  new evidence id.
