# `handoff.py`'s scaffold omits `company_key`, so 243/243 coverage decays one application at a time

- **Priority**: P2 (someday)
- **Area**: job-search
- **Source**: [workspace phase 7b](../../3_in-review/2026-07-31-workspace-phase-7b-company-key-on-meta/verification.md) — named there as the phase's one deliberate omission
- **Claimed-by**:

## Goal

Decide and implement what a newly scaffolded application's `meta.yaml` says about `company_key`,
so that full coverage is a property the tooling maintains rather than a snapshot that erodes.

## Context

Phase 7b keyed every existing application: 243 of 243 `meta.yaml` files carry a resolving
`company_key`. `handoff.py` builds a new folder's `meta.yaml` from a fixed scaffold dict which
lists `job_metadata_schema_version`, `company`, `research_date`, `channel` and `jobs` — and no
`company_key`. So every application created from now on starts unkeyed.

**Verify-with** (no line numbers — they move):

```bash
grep -n -A7 'scaffold = {' skills/job-search/scripts/handoff.py
.venv/bin/python skills/application-tracker/scripts/status.py --company-keys --strict
```

The constraint that makes this more than a one-line dict edit: `handoff.py` is public code that
runs against a **possibly-absent** overlay, so it cannot resolve a key at scaffold time. It cannot
import the index and it must not invent a key — phase 7's contract is that a key is owner-assigned
and resolves in `_index.yaml` or does not exist. Three shapes are available, and picking one is
the work:

1. leave the field absent and rely on `status.py --company-keys` reporting the gap (status quo,
   costs nothing, decays silently until someone runs the report);
2. emit `company_key:` with an empty value as a visible placeholder — note that
   `load_application` drops falsy values, so an empty string is counted **unkeyed**, not malformed,
   which is the desired reading but should be pinned by a test;
3. resolve opportunistically when the overlay happens to be mounted and the company string matches
   an index entry exactly, and leave it absent otherwise.

Whichever is chosen, the field stays **additive** — it must not enter any skip, dedup, filter or
coverage comparison (`memory/decisions/company-key-is-additive-never-a-match-key.md`), and
`automation/shared/tests/test_company_key_additive.py` is the guard that enforces it.

## Definition of done

- [ ] `handoff.py`'s scaffold behaviour for `company_key` is chosen and implemented, with the
      reason recorded in the code
- [ ] A test pins what a freshly scaffolded `meta.yaml` says about the field
- [ ] `status.py --company-keys --strict` still reports full coverage over existing applications
      and still exits 0
- [ ] The additive guard suite stays green — the scaffold change adds no match-path read
