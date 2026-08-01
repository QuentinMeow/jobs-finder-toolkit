# The keyword lists outside `location.py` still match inside a longer word

- **Priority**: P1 (this round)
- **Area**: job-search
- **Source**: adversarial audit #2, findings 3 / 7 / 9 / 12 / 23 / 29 / 33; split
  out of the branch that fixed the same class in `automation/shared/location.py`
- **Claimed-by**: <(set when work starts, before the first change)>

## Goal

Every remaining keyword list that decides a gate matches whole words, so no gate
fires on a token that merely sits inside a longer word.

## Context

`automation/shared/location.py` now matches every one of its token lists through
one compiled word-bounded alternation (`_token_pattern`, plus a containment rule
so "Mexico" inside "New Mexico" is not foreign evidence). That is the reference
implementation; this task applies the same shape to the lists it did not own.

Each of these is a bare `in` / `rfind` / `str.replace` over a phrase list, and
each was demonstrated live by the audit:

| File | Symptom | Status |
|------|---------|--------|
| `automation/shared/job_metadata.py:454` (`_TOTAL_TERMS`, used by `_compensation_range`) | `"ote"` matches inside "rem**ote**", so a base-salary band next to the word "remote" is dropped or filed as total comp | OPEN |
| `automation/shared/mail/reconciliation.py:337` (`_contains`) | `"confirmed"` matches inside "un**confirmed**" — an explicitly unconfirmed hold becomes a tracker-ready confirmed interview | OPEN |
| `automation/shared/mail/reconciliation.py:445` | bare `"opportunity"` matches the EEO footer, so every no-op status email becomes a reply TODO | DONE 2026-07-31 |
| `skills/email-assistant/scripts/application_context.py:191` | a company name matched with a trailing inflection scores +40 (threshold 20) — `"Box"` in "**boxes** were shipped", `"Stripe"` in "**stripes** on the field". *(Row corrected 2026-07-31: it said "**Meta**data" / "Drop**box**"; neither fires — see the re-measurement below.)* | OPEN |
| `skills/job-search/scripts/sources.py:285` (`_title_prefilter`) | `"intern"` matches inside "**Intern**al", dropping titles the real title gate would keep | DONE 2026-07-31 |
| `skills/job-search/scripts/scoring.py:673` (`_norm_company`) | substring replace, so the sponsor boost never fires for a legal name | DONE 2026-07-31 |
| `skills/job-search/scripts/common.py:169` | the two-letter keyword `"go"` matches "**go**-to-market" / "**go** live" | ACCEPTED — split to `tasks/0_backlog/2026-07-31-ambiguous-short-keywords-rank-on-english-prose` |

**2026-07-31 update (audit-tail branch).** Three rows are settled. The
`"opportunity"` row is fixed by subtracting the equal-opportunity legal footer
before that one cue is tested (a real "I have an opportunity for you" still
counts); the `_norm_company` row is fixed by delegating to
`registry.comparable_base`, which already strips trailing legal suffixes as whole
tokens; the `go` row is ACCEPTED with the reason recorded in `common.term_matches`
and its own backlog item. The other four were **re-verified against the current
tree and still reproduce** — `extract_salary_range` still returns `None` when the
word "remote" sits between "base salary" and the figure, an UNCONFIRMED hold still
classifies `schedule_confirmed`, `find_application_matches` still adds +40 for
`"Box"` inside "Drop**box**", and `_title_prefilter` still drops
"Software Engineer, Internal Developer Platform". They stay this task's scope.

**2026-07-31 correction (verification-regressions branch).** The `_title_prefilter`
clause in the paragraph above was **already false when it was written**: `6bec7a3`
word-anchored that list, and `6bec7a3` is an ancestor of `8699726`, the commit that
wrote the paragraph (`git show 8699726:skills/job-search/scripts/sources.py` line 339
is already `bounded_phrase_hit(...)`). It is the same defect this stack has elsewhere —
a claim measured in a `main`-based worktree and published against the stack — and it is
filed as `tasks/0_backlog/2026-07-31-pr-verification-blocks-are-measured-off-the-stack`.
The row is now DONE, with one refinement this branch adds: `manager` and `vp` keep a
space-padded entry, i.e. a WHITESPACE boundary rather than a word boundary, because bare
word-anchoring newly dropped `Software Engineer (Manager Tools)`, `Software Engineer (VP)`,
`Lead Software Engineer/Manager` and `VP, Engineering`. Three rows stay open:
`_TOTAL_TERMS`, `_contains`'s "confirmed", and `application_context`'s company match.

**2026-07-31 re-measurement of the three still-open rows (stack tip `40871e6`).** The
paragraph two above says the surviving rows "still reproduce". Driven directly against the
tip, the *mechanisms* are all real but **none of the three reproduces on the shape the row
names**. The rows stay open; their reproduction lines do not stand as written, and whoever
picks this up needs a fixture that actually fires before writing the failing test.

- **`_TOTAL_TERMS` / `"ote"` inside "remote".** The bare `'ote'` term is really in the
  tuple (`job_metadata._TOTAL_TERMS` ends `…, 'on target earnings', 'ote'`). But
  `_compensation_range("Base salary for this remote position: $150,000 - $180,000 per
  year.", total=False)` returns the full band `{'min': 150000, 'max': 180000, …}` — the
  same as the control without "remote" — and `total=True` returns `None` for both. The
  band is neither dropped nor filed as total comp on this shape.
- **`_contains` / `"confirmed"` inside "unconfirmed".** `categorize_message` on
  `"Your interview hold for Tuesday is UNCONFIRMED; we will follow up to lock it in."`
  returns `['interview_invite', 'scheduling']` — no `schedule_confirmed`. The genuinely
  confirmed control returns the same two categories, so this fixture does not separate
  them at all.
- **`application_context` / a company name inside a longer word.** The row's two examples
  do **not** fire: `_company_mentioned("Box", "we shipped a dropbox integration")` and
  `_company_mentioned("Meta", "metadata migration complete")` both return `False`. What
  does fire is the *trailing inflection* the matcher allows deliberately —
  `_company_mentioned("Box", "boxes were shipped today")` and
  `_company_mentioned("Stripe", "stripes on the field")` both return `True`. The defect is
  real; "Metadata"/"Dropbox" is the wrong description of it.

A fourth instance is already recorded separately in
`memory/known-issues/check-py-never-skill-hyphen-substring-false-positive.md`
(`check_never_skills()` flags a blocklisted word inside a hyphenated compound);
fold it in if the same helper can serve.

`reconciliation._contains` has ~30 call sites and word-boundary matching will
change some of them, so that one is the risky member of the set — the audit
recommends diffing the categories over a stored corpus and running the
email-assistant suite before merging, and it may deserve its own PR.

**Do not port `\b`.** Several phrases begin or end with punctuation, where `\b`
asserts about the wrong character; `location.py` uses
`(?<![a-z0-9]) … (?![a-z0-9])` and a longest-first alternation for exactly that
reason.

## Definition of done

- [ ] Each row above matches on word boundaries, or carries a recorded reason why
      a substring match is correct there
- [ ] One test per row, each proven to fail against the pre-fix file
- [ ] `automation/vendoring/sync_vendored.py --check` clean (all of these except
      the two `skills/job-search/scripts/` rows are vendored)
- [ ] `skills/job-search/scripts/validate_filter_variants.py` clean, with the
      salary and title shapes added to `filter_variants/corpus.yaml`
