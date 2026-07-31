# Verification — 2026-07-31-job-metadata-company-key-helper-collides

Run on 2026-07-31 from the repo root on `fix/09-company-key-loose-ends`. Absolute home paths are
redacted to `<repo-root>` and the session scratchpad to `<scratchpad>`.

## 1. Box 1 — no `company_key` symbol left that is not the persisted field

```
$ grep -n 'company_key' automation/shared/job_metadata.py
495:# NOT the owner's ``company_key``. This is a throwaway MATCH key: it exists only
498:# never compared against ``meta.yaml``'s ``company_key``, and never resolved
500:# ``_validate_company_key`` further down this same file, and the two must not be
504:# ``automation/shared/tests/test_company_key_additive.py``).
1807:    if "company_key" in record:
1809:        # above, unknown SCALARS are tolerated. So a per-job company_key would be
1815:            f"{lead}company_key is not a per-job field — one application folder is
1816:            "one employer, so company_key belongs at the top level beside company")
1828:# ``test_job_metadata.py::test_company_key_pattern_matches_the_index_module``, so a
1841:def _validate_company_key(value: Any) -> list[str]:
1847:    ``automation/shared/tests/test_company_key_additive.py``).
1861:        return ["company_key must be a lowercase company-index key "
1944:    # below), so ``company_key`` was already tolerated. This is the positive shape
1946:    errors.extend(_validate_company_key(meta.get("company_key")))
```

Every remaining occurrence is `_validate_company_key`, the `meta.yaml` field name, or prose about
one of the two. The normalizer and its local are gone:

```
$ grep -rn '_company_key(' --include='*.py' . | grep -v '\.venv\|/private/' \
      | grep -v '_validate_company_key\|_raw_company_key\|_company_match_key'
automation/shared/tests/test_job_metadata.py:849:    def test_no_surrounding_whitespace_is_tolerated_in_a_company_key(self):
automation/shared/tests/test_company_key_additive.py:414:    def test_match_paths_do_not_mention_company_key(self) -> None:
automation/shared/tests/test_company_key_additive.py:588:    def test_skip_sets_are_identical_with_and_without_company_key(self) -> None:
automation/shared/tests/test_company_key_additive.py:611:    def test_coverage_folders_are_identical_with_and_without_company_key(self) -> None:
```

Four test method names about the persisted field; no call sites.

## 2. Box 2 — identical level-lookup output, before and after

The proof is a corpus, not a new test: a rename that changed behaviour would change these
answers. `<scratchpad>/level_corpus.py` loads ONE `job_metadata` module by path, so the pre-rename
file (`git show 0fa1b0dc:automation/shared/job_metadata.py`, the branch base) and the post-rename
file run through identical harness code.

The corpus is 7744 `(company, title)` cases: every legal suffix the normalizer strips
(`incorporated|inc|llc|ltd|corp|corporation|company`, plus the dotted forms) placed LEADING,
MEDIAL, TRAILING and comma'd-trailing on 7 base names, plus blank / whitespace / uppercase /
accented / newline-carrying / double-spaced variants, crossed with 11 titles, run against two
references — the tracked `examples/profile/company-levels.example.yaml` and a synthetic cache
whose company names themselves carry suffixes in every position. Each answer is
`[company name, level name, normalized]` or `null`.

```
$ .venv/bin/python <scratchpad>/level_corpus.py <scratchpad>/job_metadata.before.py
cases      : 7744
non-None   : 1004
sha256     : 19f7f89fd8ed238e67414b6e4914892654e3fa12980df7d781cac07e44abd824

$ .venv/bin/python <scratchpad>/level_corpus.py automation/shared/job_metadata.py
cases      : 7744
non-None   : 1004
sha256     : 19f7f89fd8ed238e67414b6e4914892654e3fa12980df7d781cac07e44abd824

$ diff -q <scratchpad>/corpus.before.json <scratchpad>/corpus.after.json
IDENTICAL
```

`non-None: 1004` is the non-vacuity check — a corpus where nothing matched would hash the same
whatever the normalizer did.

## 3. Box 3 — all three vendored copies re-synced, and each gives the same answers

```
$ .venv/bin/python automation/vendoring/sync_vendored.py --check
vendored copies in sync

$ for f in skills/resume-writer/scripts/_vendor/job_metadata.py \
           skills/application-tracker/scripts/_vendor/job_metadata.py \
           skills/job-search/scripts/_vendor/job_metadata.py; do
      .venv/bin/python <scratchpad>/level_corpus.py $f | tail -1; done
sha256     : 19f7f89fd8ed238e67414b6e4914892654e3fa12980df7d781cac07e44abd824
sha256     : 19f7f89fd8ed238e67414b6e4914892654e3fa12980df7d781cac07e44abd824
sha256     : 19f7f89fd8ed238e67414b6e4914892654e3fa12980df7d781cac07e44abd824
```

Same digest as the pre-rename run, from every copy.

## 4. The comment's numbers were checked, and one was wrong

The task said `registry.comparable_base` strips 14 suffixes.

```
$ .venv/bin/python -c "import sys; sys.path.insert(0,'skills/job-search/scripts'); \
      import registry; print(len(registry._LEGAL_SUFFIXES))"
15
```

The comment names the constant and dates the count rather than restating a number that drifts.

## 5. Box 4 — additive suite, and the full gate

```
$ .venv/bin/python -m unittest discover -s automation/shared/tests \
      -p 'test_company_key_additive.py'
Ran 14 tests in 0.343s

OK
```

Full gate (`gate.sh` — the CI shape plus the export dry-run), run over the working tree carrying
both parts of this branch, immediately before they were committed. The review-gate step is the one
that cannot be green until the branch's LAST commit is acknowledged, which is what the closing
ledger-only commit is for; every other step is tip-independent.

```
$ zsh <scratchpad>/gate.sh
===== gates =====
PASS  vendor-drift
PASS  byte-compile
PASS  reconcile
PASS  leak-guard
PASS  review-gate
PASS  instruction-budget
PASS  verify-links
PASS  mail-safety
===== unit suites =====
PASS  tests:reconcile
PASS  tests:gardener
PASS  tests:hooks
PASS  tests:shared
PASS  tests:publish
PASS  tests:store-example
PASS  tests:resume-writer
PASS  tests:job-search
PASS  filter-variants
PASS  tests:app-tracker
PASS  tests:github-wf
===== export dry-run =====
PASS  export-strict

ALL GREEN
```

## What is NOT proved here

* The corpus proves `lookup_company_level` unchanged, which is the only caller of the renamed
  helper. It does not re-prove `build_job_metadata` end to end; that path is covered by the
  shared suite (455 tests, green) and by the resume-writer and tracker suites.
* Nothing here says the three normalizers SHOULD disagree — only that making them agree is a
  behaviour change and is out of scope. That measurement is still unfiled work.
