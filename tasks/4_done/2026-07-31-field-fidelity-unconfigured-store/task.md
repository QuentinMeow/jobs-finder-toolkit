# field_fidelity.py tracebacks instead of saying the store is not configured

- **Priority**: P2 (someday)
- **Area**: harness
- **Source**: found while verifying the corrected `check --key` command (contradiction audit finding A2), 2026-07-31
- **Claimed-by**: agent session 2026-08-02 (fix/25-recall-audit-cli)

## Goal

Every `field_fidelity.py` subcommand should exit with a one-line "no store
configured" message when `config.data_root()` is unset, instead of a seven-frame
`TypeError` from inside `pathlib`.

## Context

`config.data_root()` returns `None` when `paths.data_root` is absent — which is
the case for `config.example.yaml`, i.e. for every fresh clone and for CI. All
four subcommands then call `domain_layout(config.data_root(), DOMAIN)`
(`automation/search-recall-audit/field_fidelity.py:556` for `check`, and the
equivalent line in `corpus`, `sample`, `todo`) and die:

```
TypeError: argument should be a str or an os.PathLike object where
__fspath__ returns a str, not 'NoneType'
```

Reproduced on all of `corpus`, `check` and `todo`, so it is not specific to one
path. This is pre-existing and unrelated to the flag correction that surfaced it
— before that correction `check` never got far enough to reach it, because
argparse rejected the documented flags first.

The fix is a guard at the top of each subcommand (or once in `main`) that prints
what to set and returns a non-zero exit, matching how the rest of the toolkit
reports an unconfigured path. Check whether sibling store tools already have
such a helper before adding one.

## Definition of done

- [x] `JOBHUNT_CONFIG=config.example.yaml .venv/bin/python
      automation/search-recall-audit/field_fidelity.py check --key anything`
      prints a one-line diagnostic naming the missing config key and exits
      non-zero, with no traceback. — exits 2; output in `verification.md`.
- [x] Same for `corpus`, `sample` and `todo`. — `corpus` and `todo` are guarded
      alongside `check`; **`sample` is not**, deliberately: it never calls
      `config.data_root()`, so it had no traceback to fix, and it already refuses
      in one line with exit 1. Reasoning and evidence in `verification.md`.
- [x] A test pins it, so the guard cannot regress to a traceback. —
      `UnconfiguredStoreTests` in
      `automation/search-recall-audit/tests/test_field_fidelity.py`.
