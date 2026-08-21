# The sponsorship classifier still reports silence on paraphrased offers and denials

- **Priority**: P2 (someday)
- **Area**: job-search
- **Source**: GH #304, the half `fix/sponsorship-negation-safety` (2026-08-20) did not
  close
- **Claimed-by**:

## Goal

Close the recall remainder of GH #304 — sentences that state an offer or a refusal in
words neither phrase list contains, and currently produce `review` with EMPTY evidence.
GH #304's own recommendation is to stop expanding phrase lists and parse the proposition
(actor / action / object / beneficiary / modality / condition / negation / topic).

## Context

The 2026-08-20 pass closed the UNSAFE half of #304 — the readings where the classifier
asserted a definite verdict it had no right to:

- a condition fronted to the sentence ("If approved by counsel, …", "Once legal signs
  off, …") and frequency hedges ("sometimes") no longer grade as settled offers;
- `_SPONSOR_CONTEXT_RE` no longer misses the plural ("employment visas");
- the negation-to-head relation covers more than five verbs (`arrange`, `fund`,
  `coordinate`, `furnish`, `facilitate`) and its nominal forms ("has no PROGRAM for visa
  sponsorship");
- `immigration assistance` and `visa support` are offer/denial heads.

Measured after that pass on the issue's own representative failures, these two still
report `review`/`unknown` with empty evidence:

    The organization funds and coordinates employment-visa sponsorship.   (want: offer)
    Employment-visa sponsorship can be obtained from this employer.       (want: offer)

Both are the SAFE direction — `review` is kept and flagged under both policies — which is
why they were left. The obvious repair is not available: adding bare `visa sponsorship`
to `_SPONSOR_POSITIVE` would make every mention of the phrase an offer, and
"Please indicate whether you will require visa sponsorship" is a mention, not an offer.
That is a false OFFER, which is this module's expensive error.

Read before starting:

- `memory/known-issues/visa-sponsorship-negation-phrase-gap.md` — seven passes, three of
  its own prescriptions wrong in detail, and the 2026-08-20 correction on why a file's
  own reproductions cannot falsify a claim about a defect class;
- `memory/decisions/sponsorship-an-unsettled-denial-is-review-not-a-silent-drop.md` — the
  evidence-layer / verdict-layer split any repair here has to preserve;
- `skills/job-search/filter_variants/sponsorship_verdict_matrix.yaml` — 101 rows, and the
  instrument every previous pass was measured on.

## Definition of done

- The two sentences above (and paraphrases of them not used during implementation) grade
  `match`/`likely` with evidence.
- Precision is measured on held-out sentences the implementation never saw, not only on
  the corpus — the 2026-08-20 correction in the known-issue exists because replaying
  written-down sentences cannot falsify a class-level claim.
- `sponsorship_matrix.py --check` green at 101+ rows with every move recorded, and ZERO
  rows moving from a denial toward an offer.
