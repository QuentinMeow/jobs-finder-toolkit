# The leak guard arms itself with the fictional persona and blocks a legitimate export

- **Priority**: P1 (this round)
- **Area**: repo
- **Source**: parallel defect hunt, 2026-08-02; folded into the
  `fix/leak-guard-fail-open` branch because it is the same module and would
  otherwise conflict
- **Claimed-by**: implementing agent, 2026-08-02

## Goal

Stop the fictional example persona from ever being treated as the owner's real
identity, so a maintainer with `$JOBHUNT_CONFIG` exported can still publish.

## Context

Reproduction (measured, exit 1) — a clean tree, refused:

```
JOBHUNT_CONFIG="$PWD/config.example.yaml" JOBHUNT_PERSONAL_TOKENS="ZZPROBEZZ" \
  automation/publish/export_public.py --dest <scratch>
EXIT=1
  identity source:      real config (<source checkout>/config.example.yaml)
FAIL: 116 violation(s) found.
  - CONTENT AGENTS.md:12  (token: 'Jordan')  '… the fake **"Jordan Rivers"** example …'
```

Two faults compound:

1. `export_public._run_guard` builds `env = dict(os.environ)` and forwards it
   wholesale to a guard it runs with `cwd=<export dir>`. An absolute
   `$JOBHUNT_CONFIG` then points the guard's config discovery back at the SOURCE
   checkout while everything else it resolves lives in the export.
2. `check_public._identity_tokens` asked "is this the example?" by comparing two
   ABSOLUTE paths. Inside the export, `EXAMPLE_CONFIG` is the export's copy and
   the active config is the source's — the same file, two paths — so the test
   missed, and `Jordan` / `Rivers` / the example email became personal-identity
   tokens screened against the toolkit's own documentation.

`check_public.py`'s own module docstring states the opposite invariant in so many
words: the fictional example never contributes tokens.

The same root cause failed 6 tests in the publish suite whenever `$JOBHUNT_CONFIG`
was exported (`test_export_enumeration`, `test_export_destination`,
`test_leak_guard.ExporterEndToEndTests`).

## Definition of done

- [x] `_run_guard` no longer forwards `$JOBHUNT_CONFIG` into a subprocess whose
      cwd is a different tree.
- [x] Example detection is content identity, not path equality
      (`check_public.is_example_config`), so the answer travels between trees.
- [x] A REAL config that merely happens to be NAMED `config.example.yaml` is
      still treated as real — asserted by test, because the fix must not become a
      way for an owner's real identity to disarm the guard.
- [x] One predicate, three call sites (`_identity_tokens`,
      `config_identity_status`, `unarmed_report`) — the report can no longer
      disagree with the token set about which config is active.
- [x] Tests watched red before green; the publish suite green both with and
      without `$JOBHUNT_CONFIG` exported.
