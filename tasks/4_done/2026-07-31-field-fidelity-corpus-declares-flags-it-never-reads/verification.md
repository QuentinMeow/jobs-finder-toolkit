# Verification — 2026-07-31-field-fidelity-corpus-declares-flags-it-never-reads

Real output from branch `fix/25-recall-audit-cli`. Every command was redirected,
never piped, so the exit codes are the commands' own.

## No caller passes either flag — the removal breaks nothing

```
$ grep -rn 'corpus' --include='*.md' --include='*.py' --include='*.yaml' .
```

The only `field_fidelity … corpus` invocations in the tree are
`skills/search-recall-audit/SKILL.md:165` (bare, no flags) and the test module's
`_StoreCase._corpus()` helper, which built an `argparse.Namespace` carrying
`limit=600, seed=42` that `cmd_corpus` never read. Nothing else names either flag.

## Before the fix — the tests fail

```
$ .venv/bin/python -m unittest discover automation/search-recall-audit/tests \
      -k CorpusContract
EXIT=1
FAIL: test_corpus_rejects_the_sampling_flags_it_never_read (flag='--limit')
AssertionError: SystemExit not raised
FAIL: test_corpus_rejects_the_sampling_flags_it_never_read (flag='--seed')
AssertionError: SystemExit not raised
FAIL: test_the_docstring_describes_the_full_pass_corpus_actually_runs
AssertionError: 'sampled' unexpectedly found in "  Walk the derived store index,
resolve each sampled entity's RAW blob, ..."
Ran 3 tests in 0.047s
FAILED (failures=3)
```

The third test in that class — `sample` still accepts `--n`/`--seed` — passes
before AND after by design: it is the guard against over-removal, not a bug pin.

## After the fix

```
$ JOBHUNT_CONFIG=config.example.yaml .venv/bin/python \
      automation/search-recall-audit/field_fidelity.py corpus --limit 5
EXIT=2
usage: field_fidelity.py [-h] [--out OUT] {corpus,sample,check,todo} ...
field_fidelity.py: error: unrecognized arguments: --limit 5
```

Definition of done, item by item:

- [x] `corpus --limit 5` either emits at most 5 rows or the flag no longer
      exists — the flag no longer exists (output above).
- [x] The module docstring's description of `corpus` matches what it does — it
      now says a whole-RAW-zone pass deduped by blob sha, with no sampling flags,
      and no longer claims the derived index or `jd.md` lines.
- [x] A test pins whichever contract is chosen — `CorpusContractTests` in
      `automation/search-recall-audit/tests/test_field_fidelity.py`.

`skills/search-recall-audit/SKILL.md` needed no change for this task, as the task
file predicted: its `corpus` command was already flagless.

## Whole suite

```
$ .venv/bin/python -m unittest discover automation/search-recall-audit/tests
EXIT=0
Ran 34 tests in 3.202s
OK
```
