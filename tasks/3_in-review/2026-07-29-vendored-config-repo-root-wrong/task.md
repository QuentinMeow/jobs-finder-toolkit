# `REPO_ROOT` resolves inside the skill folder in every vendored `config.py`

- **Priority**: P1 (this round)
- **Area**: repo
- **Source**: found during phase 0b (`design/workspace-restructure/execution-plan.md`, item 0.12)
- **Claimed-by**: agent (session 2026-07-29, branch `fix/vendored-config-repo-root`)

## Goal

Make `REPO_ROOT` — and therefore `EXAMPLE_CONFIG` — resolve to the real repository root in the
four vendored copies of `config.py`, so that the "am I running on the fictional example?" test
stops returning a constant answer.

## Context

`automation/shared/config.py` computes `REPO_ROOT = _HERE.parent.parent`. That is correct for
the canonical copy at `automation/shared/`, but `automation/vendoring/sync_vendored.py` mirrors
the file **byte-identically** into `skills/<skill>/scripts/_vendor/config.py`, where `_HERE` is
`skills/<skill>/scripts/_vendor`. Two levels up is `skills/<skill>`, so in every vendored copy:

- `REPO_ROOT` = `skills/<skill>/`
- `EXAMPLE_CONFIG` = `skills/<skill>/config.example.yaml`, **which does not exist**

Discovery itself still works — the upward walk from `_HERE` reaches the real repo root — so this
is not user-visible as a wrong config. What it breaks is any comparison *against*
`EXAMPLE_CONFIG`:

- `skills/job-search/scripts/search_jobs.py` `_config_layer_present()` tests
  `config_path() != config.EXAMPLE_CONFIG`. Through a vendored import that is a comparison
  against a path that can never match, so it reports "a real config layer is present" even on
  an example-config run. That is the condition gating the store's "not configured" notice, so
  the notice never fires when it should.

Phase 0b deliberately left this alone: changing `REPO_ROOT` changes `EXAMPLE_CONFIG`'s identity,
and `automation/publish/check_public.py` `_identity_tokens()` uses exactly that identity to
decide whether the active config is the fictional persona. The leak guard imports the
**canonical** module, not a vendored copy, so it is unaffected today — but the two must be
reasoned about together before the constant moves.

Phase 0b already added `_search_up()`, which walks up to the first directory containing a `.git`
file or directory. That is the obvious mechanism to reuse here.

Note the constraint this interacts with: `handbook/skills-and-vendoring.md` says a skill folder
must keep working when dropped into another project. A `.git`-boundary walk satisfies that (it
finds the host project's root); a fixed parent count cannot.

## Definition of done

- In all five copies, `REPO_ROOT` resolves to the repository root and `EXAMPLE_CONFIG` points at
  a file that exists.
- A test asserts `_config_layer_present()` returns `False` when running against
  `config.example.yaml` through a **vendored** import — it returns `True` today.
- `.venv/bin/python automation/vendoring/sync_vendored.py --check` clean.
- The leak guard still distinguishes the example config from a real one:
  `automation/publish/tests/` green, including the arming tests.
