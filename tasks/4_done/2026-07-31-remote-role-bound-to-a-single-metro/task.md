# A JD remote grant that names its own residency metro reads as open US-remote

- **Priority**: P1 (this round)
- **Area**: job-search
- **Source**: a single-company `company_roles.py` re-check whose top confident
  matches were all this shape; found while answering a plain "does <company> have
  anything that fits my location policy" question.
- **Claimed-by**: agent (2026-07-31, canary-defect batch)

## Goal

Stop `assess_location` from returning a confident `match` / `us_remote` for a
posting whose JD grants remote work and then, in the same or the next sentence,
restricts residency to one metro that the policy does not prefer. The correct
verdict is `no_match` (the metro is not preferred) or, if the restriction is
ambiguous, `review` — never a silent `match`.

## Context

`automation/shared/location.py::assess_location` decides WORKPLACE from the JD
text and GEOGRAPHY from the ATS location field. When a board parks a bare
workplace word in the location field, `bare_workplace_tag` lets a JD remote grant
win (evidence `jd_remote_over_bare_workplace_tag`, ~line 640-650), the workplace
becomes `remote`, and the category becomes `us_remote` — a MATCH under any policy
with `allow_us_remote: true`.

Nothing then reads the residency clause that boards routinely attach to the same
grant:

```
This is a remote role but the location requirement is that you reside in the
<Metro>, <ST> region.
Available Location: This is a remote role but the location requirement is that
you reside in <Metro>, <ST>.
```

The grant satisfies `_REMOTE_JD_RULES` (`jd_remote_role`), the restriction is
invisible, and a candidate whose preferred metros do not include `<Metro>` is
handed a confident match. In a live single-company re-check, three of the four
confident matches were exactly this shape, each tied to a different non-preferred
metro; only one of the four was genuinely open US-remote.

This is the mirror image of the case LESSONS.md already records ("hybrid at a
non-preferred office is not generic remote") and of the backlog item
`2026-07-31-jd-body-declared-locations` (geography declared in the JD body). Both
of those move a verdict TOWARD `review`; this one is worse, because it produces a
confident MATCH the caller has no reason to re-read. The word `reside` appears
nowhere in `location.py`, `LESSONS.md`, `memory/`, or `tasks/` today.

Design sketch if picked up:

- Add a residency-restriction rule beside `_REMOTE_JD_RULES`: a remote grant
  followed within a bounded span by `reside in|located in|based in|must live in`
  plus a place. Keep the span tight, the way `jd_role_can_be_remote` does, so an
  unrelated sentence about someone else's location cannot fire it.
- When it fires, the named place — not the absent ATS location field — becomes
  the geography: `metro` if the policy prefers it, `other_us` if not, `foreign`
  if the foreign check claims it. Fall back to `review` when the place cannot be
  parsed, never to `us_remote`.
- Give it its own evidence id so an operator can see the grant was narrowed, and
  keep the asymmetry: this rule should be able to REJECT a match; it should not
  be the sole grounds for granting one.

## Definition of done

- A fictional corpus regression in `skills/job-search/filter_variants/corpus.yaml`
  covering: remote grant + `reside in <non-preferred metro>` → `no_match`; remote
  grant + `reside in <preferred metro>` → `match`; remote grant with no residency
  clause → unchanged `us_remote`.
- Unit coverage in `automation/shared/tests` for the new evidence id, and the
  vendored copies regenerated with `automation/vendoring/sync_vendored.py`
  (never edit `skills/*/scripts/_vendor/location.py` directly).
- `automation/shared/tests`, `skills/job-search/scripts/tests`, and
  `validate_filter_variants.py --check` all pass.
- One LESSONS.md line under "Location / US gate" recording the shape.
