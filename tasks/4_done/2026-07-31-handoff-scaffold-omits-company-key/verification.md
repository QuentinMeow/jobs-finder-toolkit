# Verification — 2026-07-31-handoff-scaffold-omits-company-key

Every command below was run on 2026-07-31 from the repo root on
`fix/09-company-key-loose-ends`. Absolute home paths are redacted to `<repo-root>` and the
session scratchpad to `<scratchpad>`; nothing else is edited.

## 1. Box 1 — the scaffold writes the field, and the reason is in the code

```
$ grep -n -A3 'scaffold = {' skills/job-search/scripts/handoff.py
492:    scaffold = {
493-        "job_metadata_schema_version": APPLICATION_SCHEMA_VERSION,
494-        "company": str(lead.get("company") or ""),
495-        # The owner's company-index key, ALWAYS written and ALWAYS empty here.
```

*(Corrected 2026-07-31: the first capture put the head of the block at 489 — the line it sat
on BEFORE this change added three lines above it — while numbering the rest from the new
file. 492 is the post-change line, which is what `git show dccc2ab`'s hunk header
`@@ -489,6 +492,36 @@` says too, and the command above reproduces it at head.)*

The comment that follows records three things: why the field is written (absence is invisible),
why it is empty (the index is private and the key is owner-assigned), and why `null` and not `""`
(`null` is unassigned to all three readers; `""` is malformed to all three).

## 2. Box 2 — the test pins it, and 4 of its 7 cases fail against the old scaffold

The new class is applied to the OLD `handoff.py` (`HEAD~2`), then the new one is restored.

```
$ git show HEAD~2:skills/job-search/scripts/handoff.py > <scratchpad>/handoff.base.py
$ cp <scratchpad>/handoff.base.py skills/job-search/scripts/handoff.py
$ JOBHUNT_CONFIG="$PWD/config.example.yaml" .venv/bin/python -m unittest discover \
      -s skills/job-search/scripts/tests -t skills/job-search/scripts/tests \
      -p 'test_handoff.py' -k ScaffoldedCompanyKey
ERROR: test_the_empty_key_is_null_and_not_a_blank_string
FAIL: test_handoff_says_the_key_is_empty
AssertionError: 'empty company_key' not found in 'handoff: location OK [us_remote]: Remote (US)\n'
FAIL: test_the_field_is_present_and_empty
AssertionError: 'company_key' not found in {'job_metadata_schema_version': 5, 'company':
'Nimbus Robotics', 'research_date': '2026-07-31', ...} : a scaffolded application must SAY it
is unkeyed; an absent field is indistinguishable from a considered one
FAIL: test_the_key_line_sits_directly_under_company
AssertionError: False is not true : company_key is not the line after company:
Ran 7 tests in 0.306s
FAILED (failures=3, errors=1)
```

```
$ # new handoff.py restored
$ JOBHUNT_CONFIG="$PWD/config.example.yaml" .venv/bin/python -m unittest discover \
      -s skills/job-search/scripts/tests -t skills/job-search/scripts/tests \
      -p 'test_handoff.py' -k ScaffoldedCompanyKey
Ran 7 tests in 0.307s

OK
```

The three that pass in both runs are the invariant-preservation cases (the scaffold still
validates; handoff still never imports `company_index`; the tracker still counts the application
unkeyed) — they are there to fail on a regression, not on the old behaviour.

Whole file, after:

```
$ JOBHUNT_CONFIG="$PWD/config.example.yaml" .venv/bin/python -m unittest discover \
      -s skills/job-search/scripts/tests -t skills/job-search/scripts/tests -p 'test_handoff.py'
Ran 42 tests in 1.261s

OK
```

## 3. It works with no overlay, no `config.yaml` and no index

A detached worktree in the gitignored scratch tree, which is what CI and a public clone look
like:

```
$ git worktree add --detach <scratchpad>/ci_wt HEAD
Preparing worktree (detached HEAD b6b5264)
$ ls -d <scratchpad>/ci_wt/private     ; # -> no private/  OK
$ ls    <scratchpad>/ci_wt/config.yaml ; # -> no config.yaml  OK
$ ls -d <scratchpad>/ci_wt/private/companies/_index.yaml ; # -> no company index  OK
```

Handoff run inside it, with `JOBHUNT_CONFIG` and `JOBHUNT_COMPANY_INDEX` unset:

```
$ .venv/bin/python skills/job-search/scripts/handoff.py --json <scratchpad>/demo/search.json \
      --select 'rank 1' --applications-root <scratchpad>/demo/apps --research-date 2026-07-31
handoff: meta.yaml carries an empty company_key for 'Acme Labs'. It is owner-assigned and its
index is private, so nothing here can resolve one: fill it in (adding the employer to the index
first if it is new), or leave it null and `status.py --company-keys` keeps counting this
application unkeyed.
config: no config.yaml found — using the fictional example persona at
<scratchpad>/ci_wt/config.example.yaml. ...
handoff: location OK [us_remote]: Remote (US)
<scratchpad>/demo/apps/6_drafted/acme-labs-senior-platform-engineer-20260731
meta.yaml: valid
exit=0

$ cat <scratchpad>/demo/apps/6_drafted/*/meta.yaml
job_metadata_schema_version: 5
company: Acme Labs
company_key: null
research_date: '2026-07-31'
channel: greenhouse
jobs:
- role: Senior Platform Engineer
  ...
```

`Acme Labs` is invented for this run. The whole suites, in the same worktree:

```
$ .venv/bin/python -m unittest discover -s skills/job-search/scripts/tests \
      -t skills/job-search/scripts/tests
Ran 340 tests in 12.190s
OK                                                (rc=0)

$ .venv/bin/python -m unittest discover -s automation/shared/tests
Ran 455 tests in 6.010s
OK

$ .venv/bin/python -m unittest discover -s skills/application-tracker/scripts/tests
Ran 82 tests in 17.955s
OK

$ .venv/bin/python -m unittest discover -s skills/resume-writer/scripts/tests
Ran 92 tests in 16.964s
OK

$ .venv/bin/python automation/reconcile/reconcile.py --check     # CI form, no --require-roots
reconcile: OK (8 checks clean)
$ .venv/bin/python automation/vendoring/sync_vendored.py --check
vendored copies in sync
```

## 4. Box 3 — coverage over the real tree is unchanged

```
$ .venv/bin/python skills/application-tracker/scripts/status.py --company-keys --strict
company keys: 243 applications, 214 distinct company strings
  keyed:       243  (208 distinct keys)
  unkeyed:     0
  malformed:   0    -> company_key present but not a key
  unresolved:  0    -> company_key not in the index
exit=0
```

## 5. Box 4 — the key is still additive

The whole invariant suite, and the job-search skip-identity suite beside it:

```
$ .venv/bin/python -m unittest discover -s automation/shared/tests \
      -p 'test_company_key_additive.py'
Ran 14 tests in 0.343s

OK

$ JOBHUNT_CONFIG="$PWD/config.example.yaml" .venv/bin/python -m unittest discover \
      -s skills/job-search/scripts/tests -t skills/job-search/scripts/tests \
      -p 'test_skip_identity.py'
Ran 19 tests in 0.033s

OK
```

And the reason it stays green: no guarded root in `handoff.py` can reach the function that now
writes the field. Driven through the suite's own closure walker, so it is the same walk the guard
performs:

```
$ .venv/bin/python  # _closure_paths / _field_mentions from test_company_key_additive.py
_posting_keys      closure=['_norm', '_posting_keys']
                   build_meta_bytes reachable = False
                   company_key mentions in closure = []
_duplicate_reason  closure=['_duplicate_reason', '_norm']
                   build_meta_bytes reachable = False
                   company_key mentions in closure = []
_register_row      closure=['_norm', '_register_row']
                   build_meta_bytes reachable = False
                   company_key mentions in closure = []
group_by_company   closure=['_norm', 'group_by_company']
                   build_meta_bytes reachable = False
                   company_key mentions in closure = []
```

`build_meta_bytes` spells `company_key` out, so if anyone ever wires it into one of those
closures the existing guard goes red with no new machinery — the naming does the work.

## 6. Full gate

See `verification.md` in the sibling task
(`2026-07-31-job-metadata-company-key-helper-collides`) — one run covers both halves of this
branch.

## What is NOT proved here

* Nothing measures how often a NEW application's company already has an index entry; the
  208-distinct-keys-over-243-applications figure above is a proxy read off the existing tree, and
  it is the basis for calling opportunistic resolution low-value rather than a measurement of it.
* The stderr line is pinned by a test on its content, not on its usefulness. It prints once per
  scaffolded folder, every time, including for a company that is about to be keyed by hand
  seconds later.
