# Verification — 2026-07-31-workspace-phase-7b-company-key-on-meta

The work landed in the private overlay repo (its own remote; PR #63). This file is the public
record of it. **Every command below was re-run on 2026-07-31 by the agent writing this file** —
nothing here is copied from the implementing session's report. Where that report made a claim this
agent could not reproduce, it is named as unverified rather than restated.

No company name, application slug or company key appears here — shapes and counts only.

## The result the phase exists for

```
$ .venv/bin/python skills/application-tracker/scripts/status.py --company-keys --strict
company keys: 243 applications, 214 distinct company strings
  keyed:       243  (208 distinct keys)
  unkeyed:     0
  unresolved:  0    -> company_key not in the index
exit 0
```

Cross-checked against the files themselves rather than trusting the reporter:

```
$ find <applications-root> -name meta.yaml | wc -l
243
$ grep -l '^company_key:' $(find <applications-root> -name meta.yaml) | wc -l
243
$ .venv/bin/python -c "... company_index.load(<index>) ..."
keys: 222
```

243 of 243 application `meta.yaml` files carry a `company_key`, all 243 resolve in the 222-key
index phase 7 shipped, and 214 distinct company strings collapse to 208 distinct keys — the six
that collapse are alias merges the index already records. Zero unresolved, so no key was guessed
and no index entry was invented.

## One added line per file, nothing reflowed

```
$ git -C <overlay> show --numstat --format="" <the keying commit> | wc -l
243
$ git -C <overlay> show --numstat --format="" <the keying commit> | awk '{print $1"/"$2}' | sort | uniq -c
 243 1/0
```

**Every one of the 243 files is exactly +1 / −0.** Zero deletions across the whole commit, so no
file was re-serialised, no comment or quoting style was lost, and no key order changed. That is
the box "no file was reflowed", proved by the diff itself rather than by inspection.

## The key is additive: no skip decision moved

Unit level:

```
$ .venv/bin/python -m unittest discover -s automation/shared/tests -p 'test_company_key_additive.py'
Ran 6 tests in 0.438s   OK

$ JOBHUNT_CONFIG=<repo>/config.example.yaml .venv/bin/python -m unittest discover \
      -s skills/job-search/scripts/tests -t skills/job-search/scripts/tests -p 'test_skip_identity*.py'
Ran 19 tests in 0.053s   OK
```

Measured on the real tree as well, not only on fixtures. A detached overlay worktree was checked
out at the commit **before** the keying commit (no keys anywhere), and `handoff._posting_keys` —
the function that decides what a search skips — was run against both trees with the same log:

```
$ git -C <overlay> worktree add --detach <scratch> <keying-commit>^
$ .venv/bin/python -c "... handoff._posting_keys(current_root, log) vs (parent_root, log) ..."
urls  identical: True  367 367
pairs identical: True  369 369
SKIP SET IDENTICAL: True
$ git -C <overlay> worktree remove --force <scratch>
```

367 posting URLs and 369 (company, role) pairs, identical both ways. A search run after this
change skips exactly what it would have skipped before it. This is the load-bearing safety claim
of the phase and it reproduces.

The same 369/367 figures come out of the append-only skip-log independently:

```
$ .venv/bin/python -c "... json lines from config.applications_jsonl_path() ..."
events: 369
distinct urls: 367
```

## Gates

```
$ .venv/bin/python automation/reconcile/reconcile.py --check --require-roots
reconcile: OK (9 checks clean)                        exit 0

$ .venv/bin/python skills/application-tracker/scripts/status.py --check-metadata
Checked 243 applications; 0 invalid.                  exit 0
```

The reconciler's company-key check was passing vacuously before this task — nothing carried the
field for it to verify. It now verifies 243 keys and stays clean.

## What this agent could NOT verify, stated rather than restated

(One of the two entries below has since been verified after all; it is corrected in place rather
than deleted, so the record shows what was checked and when.)

- **The per-file pre-write / post-write round-trip assertion, and its "0 failures, 0 reverts"
  count.** That is a property of the run, not of the tree, and it left no artifact. What the tree
  proves instead — and proves more strongly — is the outcome the assertion existed to guarantee:
  every file still parses (`--check-metadata` 243/243 valid), and the diff is +1/−0 on every file.
  The box is ticked on that evidence, and this limitation is why the wording is recorded here.
- ~~**The diff against the proposal-era `meta_updates.tsv`.**~~ **Corrected 2026-07-31, and the
  diff was run.** The TSV is tracked by neither repository — that part stands:

  ```
  $ git log --all --name-only --format='' | grep -c 'meta_updates.tsv'   # public
  0
  $ git -C <overlay> log --all --name-only --format='' | grep -c 'meta_updates.tsv'
  0
  ```

  But it survives in the implementing session's scratchpad, and an independent agent has since
  diffed its 243 rows against the `company_key` each `meta.yaml` actually carries:

  ```
  $ .venv/bin/python -c "<read the TSV; compare proposed_company_key against the committed
                          company_key in each meta.yaml>"
  tsv rows: 243
  agree: 242  disagree: 1  unlocatable: 0
  ```

  **Exactly one row disagrees, and it is the expected one**: the joint-venture folder the owner's
  ruling moved, where the proposal assigned the joint venture its own key and the committed file
  carries the parent brand's. So the mapping is the index **as committed**, not a stale copy, and
  the single divergence is the owner's decision rather than drift. The TSV holds real employer
  names and is deliberately not copied into either repository, which is why only shapes and counts
  appear here. This entry originally read "unfollowable as written"; it understated what could be
  checked.

## Definition of done — what is and is not covered

Ticked on the evidence above: every application keyed and resolving; `--require-roots` clean with
the overlay mounted; `--company-keys --strict` at full coverage, exit 0; skip-set identity green at
unit level **and** measured on the real tree; one added line per file, no reflow. The round-trip
assertion box is ticked on outcome evidence, with the caveat recorded above.

**Deliberately not done, and named rather than dropped:** `handoff.py` builds a new folder's
`meta.yaml` from a fixed scaffold dict (`skills/job-search/scripts/handoff.py:489`), which lists
`job_metadata_schema_version`, `company`, `research_date`, `channel` and `jobs` — and no
`company_key`. So a NEW application will not carry the field, and today's 243/243 coverage decays
one application at a time. It is public code that runs against a possibly-absent overlay and so
cannot resolve a key at scaffold time; leaving the field absent is the documented normal state for
a new application, and `status.py --company-keys` is the surface that reports it. Filed as its own
public task: `2026-07-31-handoff-scaffold-omits-company-key`.
