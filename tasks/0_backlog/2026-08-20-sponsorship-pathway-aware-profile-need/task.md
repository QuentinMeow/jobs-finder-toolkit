# The profile cannot say WHICH sponsorship pathway the candidate needs

- **Priority**: P1 (this round)
- **Area**: job-search
- **Source**: GH #265, the half `fix/sponsorship-negation-safety` (2026-08-20) could
  not close from inside the classifier
- **Claimed-by**:

## Goal

`visa.needs_sponsorship` is a boolean, so a posting that accepts an H-1B TRANSFER but
cannot file a NEW cap-subject petition reads the same for every candidate. Give the
profile a way to name the pathway, and let `assess_sponsorship` / `visa_ok` answer for
that pathway instead of collapsing both into one verdict.

## Context

GH #265 asks for exactly this: *"For `needs_sponsorship: H-1B transfer`, an explicit
transfer-positive statement should be eligible/likely even when new initial petitions are
unavailable. For a candidate needing a new cap-subject petition, the same posting should
be unlikely."*

What already exists, after the 2026-08-20 pass:

- `automation/shared/job_metadata.py` detects both halves. A denial lexically scoped to a
  new/initial/cap-subject PETITION is recognized (`_sponsor_denial_scoped_to_new_petitions`,
  `_SPONSOR_NEW_PETITION_RE`), and an explicit transfer welcome is now an OFFER phrase
  (`h-1b transfer` / `h-1b transfers` in `_SPONSOR_POSITIVE`).
- With both present the posting therefore lands `review`/`unknown`/low — the fallback the
  issue explicitly allows ("If profile schema cannot yet express the distinction, return a
  scoped conflict/review rather than a universal hard negative"). Pinned by
  `automation/shared/tests/test_sponsorship_transfer_scope.py` and the
  `transfer-friendly-new-petition-denial` matrix row.

So the classifier is not the blocker. The blocker is that nothing downstream can ask a
pathway question:

- `config.example.yaml` / the profile schema carry `visa.needs_sponsorship` (bool) and
  `visa.policy` (`exclude_negative` | `require_positive`);
- `skills/job-search/scripts/scoring.py::visa_ok` reads only those two;
- `assess_sponsorship(text)` takes no candidate argument at all, so its verdict cannot
  depend on the reader.

Design constraint that outranks convenience: this module's whole history
(`memory/known-issues/visa-sponsorship-negation-phrase-gap.md`, six passes) is one
direction being fixed by reopening the other. A pathway argument must not become a way
to PROMOTE a posting — a transfer-needing candidate seeing `likely` on a transfer-friendly
posting is fine; anything that turns a settled refusal into an offer for anyone is not.

## Definition of done

- The profile can express at least `transfer`, `new_petition`, and "unspecified"
  (unspecified must behave exactly as `needs_sponsorship: true` does today — measure it,
  do not assume it).
- Cross-product regression over the four JD shapes GH #265 names (transfers accepted +
  new petitions unavailable; cap-exempt only; extensions accepted + initial sponsorship
  unavailable; all H-1B sponsorship unavailable) against all three needs, asserting a
  pathway-specific decision and its evidence.
- `skills/job-search/scripts/sponsorship_matrix.py --check` green, with every row that
  moves carrying an `expect` block and a note; a row whose text names no pathway must not
  move at all.
- The unspecified/legacy path is byte-identical on the whole matrix.
