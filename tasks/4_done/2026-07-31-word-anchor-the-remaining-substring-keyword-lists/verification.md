# Verification — 2026-07-31-word-anchor-the-remaining-substring-keyword-lists

Retro-closure, 2026-08-02. The three rows the task still listed OPEN
(`_TOTAL_TERMS`, `reconciliation._contains`'s `"confirmed"`,
`application_context`'s company match) were fixed by `b18c9c5`, "Stop five phrase
lists matching inside longer words", an ancestor of `f360aec`.

```
$ git merge-base --is-ancestor b18c9c5 HEAD; echo $?
0
$ git show --stat --oneline b18c9c5 | head -8
b18c9c5 Stop five phrase lists matching inside longer words
 automation/shared/job_metadata.py                  |  21 +-
 automation/shared/mail/reconciliation.py           |  66 +++++-
 automation/shared/tests/test_job_metadata.py       |  25 ++
 .../scripts/_vendor/mail/reconciliation.py         |  66 +++++-
 .../email-assistant/scripts/application_context.py |  23 +-
 .../scripts/tests/test_application_context.py      |  37 +++
```

## DoD 1 — each row matches on word boundaries, or records why not

- **`_TOTAL_TERMS` / `"ote"` inside "remote"** — `automation/shared/job_metadata.py:1131-1137`
  now uses `_last_bounded_start` / `_bounded_phrase_matches` instead of
  `rfind`/`in`, with the reason at the call site: *"`_TOTAL_TERMS` carries the
  bare token 'ote' (on-target earnings), and an unanchored scan finds it inside
  'rem-OTE-'."*
- **`reconciliation._contains`** — now `return any(_bounded_phrase_hit(text, phrase) ...)`,
  docstring: *"True if any phrase occurs as a bounded phrase — never as a bare
  substring."*
- **`application_context._company_mentioned`** — rewritten to
  `(?<![a-z0-9]) … (?:s|es)?(?![a-z0-9])`, with the recorded reason for the one
  substring behaviour it deliberately keeps: *"A trailing inflection is fine
  ('Acme's', 'Acmes'); 'Dropbox' is not a mention of 'Box'."* That discharges the
  bullet's "or carries a recorded reason" branch.

## DoD 2 — one test per row

```
$ grep -rn "remote position\|Internal Developer Platform\|UNCONFIRMED\|boxes were shipped" \
    automation/shared/tests/ skills/email-assistant/scripts/tests/ skills/job-search/scripts/tests/
automation/shared/tests/test_job_metadata.py:278:  # inside "rem-OTE-", so an ordinary "this is a fully remote position"
skills/job-search/scripts/tests/test_title_word_filter.py:135:  cases = (("intern", "Software Engineer, Internal Developer Platform"),
skills/email-assistant/scripts/tests/test_stored_mail_reconciliation.py:374:  "REQ-123: this is an UNCONFIRMED hold for 2026-08-05 2:00 PM PT. "
skills/job-search/scripts/tests/test_sources_intake.py:68:  "Software Engineer, Internal Developer Platform",
```

## DoD 3 — vendoring clean

```
$ .venv/bin/python automation/vendoring/sync_vendored.py --check; echo "EXIT=$?"
EXIT=0
```

## DoD 4 — filter-variant validator clean; corpus shapes

```
$ .venv/bin/python skills/job-search/scripts/validate_filter_variants.py; echo "EXIT=$?"
EXIT=0
```

(It exited **1** in all four search runs recorded in
`evals/results/job-search-40871e6799a0-20260731-stack-head.md`; it is green now.)

**Deviation, recorded rather than papered over:** the corpus at
`skills/job-search/filter_variants/corpus.yaml` carries 16 `domain: title`
variants but **no salary domain at all** —

```
$ grep "domain:" skills/job-search/filter_variants/corpus.yaml | sort | uniq -c
  30     domain: location
   4     domain: quality
  25     domain: sponsorship
  16     domain: title
   9     domain: yoe
```

so the "salary shape" half of this bullet is not expressible in that file today.
The salary regression is covered instead by a unit test at
`automation/shared/tests/test_job_metadata.py:278`. Adding a salary domain to the
variant corpus is a separate change and is not claimed here.

## Still open elsewhere (not regressions of this task)

The `"go"` row was ACCEPTED and split to
`tasks/0_backlog/2026-07-31-ambiguous-short-keywords-rank-on-english-prose`; the
`check_never_skills` hyphen case remains in
`memory/known-issues/check-py-never-skill-hyphen-substring-false-positive.md`.
Both were already outside this task's row list.
