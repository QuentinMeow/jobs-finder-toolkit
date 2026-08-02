# Verification — 2026-07-31-field-fidelity-unconfigured-store

Real output, captured on branch `fix/25-recall-audit-cli` in a worktree with no
`config.yaml` and no `private/` overlay, so `config.data_root()` is `None` exactly
as it is in a fresh clone. Commands were redirected, never piped, so every exit
code below is the gate's own.

## Before the fix — the reproduction in the task file

```
$ JOBHUNT_CONFIG=config.example.yaml .venv/bin/python \
      automation/search-recall-audit/field_fidelity.py check --key anything
EXIT=1
Traceback (most recent call last):
  File ".../field_fidelity.py", line 761, in <module>
    raise SystemExit(main())
  File ".../field_fidelity.py", line 756, in main
    args.func(args)
  File ".../field_fidelity.py", line 673, in cmd_check
    layout = domain_layout(config.data_root(), DOMAIN)
  File ".../store/paths.py", line 126, in domain_layout
    return DomainLayout(root=Path(data_root) / domain, domain=domain)
  ...
TypeError: argument should be a str or an os.PathLike object where
__fspath__ returns a str, not 'NoneType'
```

The new tests fail against that code, in the same frame — a test that passed
before the fix would not be testing the fix:

```
$ .venv/bin/python -m unittest discover automation/search-recall-audit/tests \
      -k UnconfiguredStore -k OutputContainment
EXIT=1
.EEE.E
ERROR: test_every_store_reading_command_names_what_to_configure (cmd='corpus')
ERROR: test_every_store_reading_command_names_what_to_configure (cmd='check')
ERROR: test_every_store_reading_command_names_what_to_configure (cmd='todo')
ERROR: test_the_refusal_leaves_the_scratch_dir_unwritten
  ...
  File ".../field_fidelity.py", line 508, in cmd_corpus
    layout = domain_layout(config.data_root(), DOMAIN)
TypeError: argument should be a str or an os.PathLike object ... not 'NoneType'
Ran 4 tests in 0.087s
FAILED (errors=4)
```

## After the fix — every store-reading subcommand

```
$ JOBHUNT_CONFIG=config.example.yaml .venv/bin/python \
      automation/search-recall-audit/field_fidelity.py check --key anything
EXIT=2
check: store not configured (set paths.data_root in config.yaml or export
JOBHUNT_DATA_ROOT) — this command reads the raw zone.

$ ... field_fidelity.py corpus
EXIT=2
corpus: store not configured (set paths.data_root in config.yaml or export
JOBHUNT_DATA_ROOT) — this command reads the raw zone.

$ ... field_fidelity.py todo
EXIT=2
todo: store not configured (set paths.data_root in config.yaml or export
JOBHUNT_DATA_ROOT) — this command reads the raw zone.

$ ... field_fidelity.py sample
EXIT=1
missing .../local/field_fidelity_audit/corpus.jsonl — run `corpus` first.
```

**`sample` is deliberately unguarded** and this is the one departure from the
task's definition of done. It never calls `config.data_root()`; it reads the
corpus file `corpus` wrote under `local/`. Its refusal is already one line, exit
1, no traceback, and it names the real next step — which then reports the store
problem. Gating it on the store would assert a dependency it does not have. A test
pins that reading (`test_sample_reads_only_the_scratch_corpus_so_it_needs_no_store`).

## The pin

```
$ .venv/bin/python -m unittest discover automation/search-recall-audit/tests
EXIT=0
Ran 31 tests in 2.662s
OK
```

Three of those are new: the per-command refusal (subtested over `corpus`,
`check`, `todo`), that a refused run leaves the scratch dir unwritten, and
`sample`'s store-free refusal. Nothing but `SystemExit` is caught in the test
helper, so a returning traceback reaches the runner as an error rather than being
absorbed into a pass.
