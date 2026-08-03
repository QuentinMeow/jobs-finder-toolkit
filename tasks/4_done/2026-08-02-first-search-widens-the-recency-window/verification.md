# Verification — 2026-08-02-first-search-widens-the-recency-window

Retro-closure, 2026-08-02. The code and two of the three documents shipped in
`16d2878`; the third (`skills/job-search/profiles/README.md`) was still on the old
contract and is fixed in the same commit that closes this task.

```
$ git merge-base --is-ancestor 16d2878 HEAD; echo $?
0
$ git log --oneline -1 16d2878
16d2878 Move the title filter's words into the profile, and widen a first search
```

## DoD 1 — no age gate on a first search; profile window on a repeat

`skills/job-search/scripts/search_jobs.py`:

```
536: def is_first_search(p, token_dates, registry=None) -> bool:
         """True when this employer has NEVER completed a successful full-board search."""
...
849:        if widening_active and is_first_search(p, ctx["search_tokens"], registry):
850:            effective_max_age = first_search_max_age
851:            if not date_ok(p, max_age) and date_ok(p, effective_max_age):
852:                n_first_search_widened += 1
853:        if not date_ok(p, effective_max_age):
854:            continue
```

`widening_active` (`:801-802`) requires `widen_first_search` on, a profile
`max_age` set, and a different first-search window — so a profile with
`max_age_days: null` is unaffected. Both directions are exercised by
`skills/job-search/scripts/tests/test_title_word_filter.py` (the file that also
carries the `is_first_search` cases).

```
$ .venv/bin/python automation/gates/run_gates.py
  PASS   tests-job-search  exit 0    78.0s
```

## DoD 2 — the run header names the widened window

`search_jobs.py:1001-1005`:

```
    if meta.get("n_first_search_widened"):
        first = meta.get("first_search_max_age_days")
        ...
        f"First search: {meta['n_first_search_widened']} posting(s) kept by the "
```

## DoD 3 — SKILL.md, reference.md and profiles/README.md state the rule

```
$ grep -n "first search\|first_search" skills/job-search/SKILL.md skills/job-search/reference.md
skills/job-search/SKILL.md:91:  **A company's FIRST search is not age-filtered.** ...
skills/job-search/reference.md:279:| `widen_first_search` | `true` | `false` = one window for every run |
skills/job-search/reference.md:280:| `first_search_max_age_days` | `null` | `null` = no posting-age filter at all on a first search
skills/job-search/reference.md:289:  employer whose row was never written reads as first-search and gets the wide
```

`skills/job-search/profiles/README.md`'s `max_age_days` entry still described the
window as applying to every run with no first-search exception. **Fixed in the
closing commit** — it now names the exception and points at `reference.md`
§ Recency filter. That one line was the only residual.

## DoD 4 — reconciler and suite green

```
$ .venv/bin/python automation/reconcile/reconcile.py --check; echo "EXIT=$?"
reconcile: OK (9 checks clean)
EXIT=0
```

## Eval gate

`skills/job-search/profiles/README.md` is not a `SKILL.md`/`LESSONS.md`/`reference.md`
file, so the risk-based eval gate does not fire on this closure. The behavioural
edits it documents shipped in `16d2878` and carry that PR's own discharge.
