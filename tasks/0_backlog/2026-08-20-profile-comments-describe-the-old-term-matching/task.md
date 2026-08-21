# Profile comments still describe term matching as word-boundary only

- **Priority**: P2 (someday)
- **Area**: job-search
- **Source**: the GH #298 / #279 term-matching fix (branch
  `fix/term-matching-precision`), which changed the behaviour those comments
  summarize but was scoped to `common.py` + its tests
- **Claimed-by**: <(set when work starts, before the first change)>

## Goal

The two profile files a user copies describe how `titles.include` and
`titles.exclude` actually match, so nobody writes a redundant hyphen spelling or
wonders why a keyword stopped scoring.

## Context

`common.term_matches` now does three things those one-line comments do not
mention:

- **Separators are equivalent.** `front end engineer` matches `Front-End
  Engineer` and every Unicode-dash spelling, so a profile no longer needs a line
  per hyphenation. It does NOT match `Frontend Engineer` — the closed spelling is
  still its own entry, as the example profile already shows for `fullstack` /
  `full stack`.
- **A trailing English inflection counts**, so `data scientist` also matches
  *Data Scientists* — the same allowance `word_filter` already documents for
  `recruit` / *Recruiter*.
- **An ambiguous term needs context.** `go` scores only where the surrounding
  words read as the language, so a JD saying only "go-to-market" no longer earns
  `strong: go`. (`_AMBIGUOUS_TERM_GUARDS` in `skills/job-search/scripts/common.py`.)

The stale lines are:

- `skills/job-search/profiles/example.yaml:16` — `# title must contain at least
  one (case-insensitive, word-boundary)`
- `skills/job-search/profiles/_TEMPLATE.yaml:9` — `# title must contain >=1 of
  these (word-boundary, case-insensitive)`

Neither is WRONG, so nothing is broken; they are just silent about the part a
novice would otherwise get wrong by duplicating spellings. Check whether
`skills/job-search/SKILL.md` or `reference.md` needs the same sentence while you
are there — a `SKILL.md` edit carries the risk-based eval-gate decision.

## Definition of done

- [ ] Both profile comments state the separator equivalence and its bound
      (equivalent, not elidable)
- [ ] Whichever of `SKILL.md` / `reference.md` explains the title gate says the
      same thing, or is confirmed to say nothing that contradicts it
- [ ] Eval-gate decision recorded in the PR if a harness file was touched
