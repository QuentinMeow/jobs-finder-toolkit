# `baseline_path()` can diverge from `candidate_dir()` when only one key is configured

- **Priority**: P2 (someday)
- **Area**: repo
- **Source**: found during phase 0b (`docs/designs/workspace-restructure/execution-plan.md`, item 0.12)
- **Claimed-by**:

## Goal

Decide whether `baseline_path()`'s default should be derived from `candidate_dir()` like its
siblings, and make it so — or record why it deliberately is not.

## Context

Phase 0b added `candidate_dir()` and routed `tailoring_card_path()`,
`applications_log_path()`, `company_search_log_path()` and `calendar_path()`'s derived branch
through it. `baseline_path()` was left alone because changing it moves a path, which is out of
scope for a phase whose job was to stop checks failing open.

Today `baseline_path()` resolves the literal `"applications/0_profile/baseline.yaml"` relative
to the **config file's directory**. So it agrees with `candidate_dir() / "baseline.yaml"` only
when `paths.applications_root` is unset or happens to equal `applications`. Set
`paths.applications_root: private/applications` and leave `paths.baseline_yaml` unset — which
is a legal config — and the two disagree: `candidate_dir()` gives
`private/applications/0_profile/`, while `baseline_path()` gives `applications/0_profile/`
relative to the config dir.

The live `config.yaml` sets `paths.baseline_yaml` explicitly, so this is latent, not active.
It becomes active for anyone who configures `applications_root` alone — and phase 5 moves the
baseline to `private/me/baseline.yaml`, so whoever does that work will meet this.

`profile_md_path()` and `reference_docx_path()` have the same shape (a literal default relative
to the config dir) but point at `examples/`, which is deliberate — those defaults are the
fixture data, not a derived location. `baseline_path()` is the odd one out because its default
names a directory that `candidate_dir()` now owns.

## Definition of done

**Resolved 2026-08-06:** `baseline_path()` now uses the same config-dir-relative fictional
fixture strategy as the profile and reference DOCX. A code comment records why it deliberately
does not derive from `candidate_dir()`, and accessor tests pin the public and explicit real paths.

Either:

- `baseline_path()`'s default becomes `candidate_dir() / "baseline.yaml"`, with a test asserting
  the two agree for a config that sets only `paths.applications_root`; or
- a comment in `automation/shared/config.py` states why it stays config-dir-relative, and this
  task is closed as won't-fix.

Whichever way: `.venv/bin/python automation/vendoring/sync_vendored.py --check` clean, and
`skills/resume-writer/scripts/tests/` green.
