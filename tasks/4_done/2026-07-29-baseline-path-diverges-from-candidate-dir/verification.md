# Verification — 2026-07-29-baseline-path-diverges-from-candidate-dir

## Accessor behavior and vendoring

```
$ .venv/bin/python automation/shared/tests/test_config_accessors.py
Ran 27 tests in 0.129s

OK

$ .venv/bin/python automation/vendoring/sync_vendored.py --check
vendored copies: in sync
```
