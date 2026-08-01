# A profile keyword that is also an English word ranks on ordinary prose

- **Priority**: P2 (someday)
- **Area**: job-search
- **Source**: adversarial audit #2, finding 33; triaged as ACCEPTED (not fixed) by
  the branch that cleared the audit's tail, with the reason recorded in
  `skills/job-search/scripts/common.py` (`term_matches` docstring)
- **Claimed-by**: <(set when work starts, before the first change)>

## Goal

A profile can say "Go, the programming language" without also matching
"go-to-market", "go live" and "go above and beyond".

## Context

`common.term_matches` builds `\b<term>\b` for any single alphanumeric token, which
is the strongest match it can express. `skills/job-search/profiles/example.yaml`
ships `go` in `keywords.strong`, so a pure Ruby posting whose JD says "go-to-
market" earns `strong: go` (+4, or +8 when the word is in the title).

Measured effect: score only. Keywords never gate — no posting is dropped or kept
because of one — so the whole cost is a few points of ranking noise on a row that
was already going to appear. `\b` already handles the cases that matter: `java`
correctly does not match *javascript*, and `ml` / `ai` / `api` are fine.

**Why it was not fixed in the audit-tail branch.** Every fix worth having is a
new per-keyword profile field (`phrase_only`, or a required-companion list like
`go` + `golang|goroutine|go modules`). That is a profile-SCHEMA change: the
example profile, the profile loader, `validate_filter_variants`, and every
private profile move together, and the schema then has to answer "what happens
when an old profile omits the field". A repo this heavily gated pays for every
change in review surface, and this one buys back a +4 nudge.

Pick this up when a profile change is already in flight for another reason, or
when a real search shows the noise actually reordering a shortlist.

## Definition of done

- [ ] A profile can express an ambiguous short keyword unambiguously (design
      choice open: phrase-only flag, companion-term requirement, or a regex form)
- [ ] `skills/job-search/profiles/example.yaml` uses it for `go`
- [ ] One test proving a "go-to-market" JD no longer scores `strong: go`, and one
      proving a genuine Go posting still does
- [ ] `skills/job-search/scripts/validate_filter_variants.py --check` clean
