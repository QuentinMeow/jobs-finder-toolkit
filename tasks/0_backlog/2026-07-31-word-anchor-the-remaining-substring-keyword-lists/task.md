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

| File | Symptom |
|------|---------|
| `automation/shared/job_metadata.py:454` (`_TOTAL_TERMS`, used by `_compensation_range`) | `"ote"` matches inside "rem**ote**", so a base-salary band next to the word "remote" is dropped or filed as total comp |
| `automation/shared/mail/reconciliation.py:337` (`_contains`) | `"confirmed"` matches inside "un**confirmed**" — an explicitly unconfirmed hold becomes a tracker-ready confirmed interview |
| `automation/shared/mail/reconciliation.py:445` | bare `"opportunity"` matches the EEO footer, so every no-op status email becomes a reply TODO |
| `skills/email-assistant/scripts/application_context.py:191` | a company name inside a longer word scores +40 (threshold 20) — "**Meta**data", "Drop**box**" |
| `skills/job-search/scripts/sources.py:285` (`_title_prefilter`) | `"intern"` matches inside "**Intern**al", dropping titles the real title gate would keep |
| `skills/job-search/scripts/scoring.py:673` (`_norm_company`) | substring replace, so the sponsor boost never fires for a legal name |
| `skills/job-search/scripts/common.py:169` | the two-letter keyword `"go"` matches "**go**-to-market" / "**go** live" |

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
