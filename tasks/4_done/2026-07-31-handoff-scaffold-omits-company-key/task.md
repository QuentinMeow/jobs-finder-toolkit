# `handoff.py`'s scaffold omits `company_key`, so 243/243 coverage decays one application at a time

- **Priority**: P2 (someday)
- **Area**: job-search
- **Source**: [workspace phase 7b](../../3_in-review/2026-07-31-workspace-phase-7b-company-key-on-meta/verification.md) — named there as the phase's one deliberate omission
- **Claimed-by**: agent (PR 09, company-key loose ends), 2026-07-31

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

## Decision (2026-07-31) — shape 2, and shape 3 was rejected

**Chosen: shape 2.** The scaffold always writes `company_key: null`. `null` is the state
`validate_meta`, the reconciler's company-index check and `--company-keys` already agree means
UNASSIGNED (a blank string is malformed to all three), so nothing new had to be taught the
semantics. `handoff` also prints one stderr line per folder naming the gap and the remedy, so the
gap is reported when it is CREATED — the coverage report is the surface that already existed, and
it is the one that let coverage decay unnoticed.

**Shape 1 (status quo) rejected**: absence carries no information. An application with no field is
indistinguishable from one whose key was considered and rejected, and nothing says so until
somebody runs a report.

**Shape 3 (opportunistic resolve) rejected**, and this is the one worth writing down:

* it makes the BYTES of a new `meta.yaml` depend on whether the overlay happened to be mounted,
  so the same posting scaffolded twice produces two different files;
* it puts an index reader inside the module that holds four of the additive guard's roots, and a
  future call to `company_index.resolve(...)` from a match path would spell no literal the
  textual guard looks for;
* it needs `company_index` vendored into job-search, reversing the deliberate ONE-copy decision
  recorded in `automation/vendoring/sync_vendored.py`;
* and it buys less than it looks like. Over the tree as it stands — 243 applications, 214
  distinct company strings, 208 distinct keys — most new applications are at an employer the
  index does not yet carry, and those need an owner-assigned key regardless. It would pre-fill a
  minority of cases without removing a single step from the owner's workflow.

A separate `status.py` subcommand that keys the unkeyed was left alone: assigning a key is the
owner's judgement, and the repair surface for a wrong or missing one is the index plus a one-line
edit, not another writer.

## Definition of done

Evidence in [`verification.md`](verification.md) beside this file.

- [x] `handoff.py`'s scaffold behaviour for `company_key` is chosen and implemented, with the
      reason recorded in the code — the long comment on the scaffold dict records both the choice
      and why `null` rather than `""`
- [x] A test pins what a freshly scaffolded `meta.yaml` says about the field —
      `test_handoff.py::ScaffoldedCompanyKeyTests`, 7 cases; 4 of them fail against the old
      scaffold
- [x] `status.py --company-keys --strict` still reports full coverage over existing applications
      and still exits 0 — 243 keyed / 0 unkeyed / 0 malformed / 0 unresolved
- [x] The additive guard suite stays green — the scaffold change adds no match-path read; no
      handoff guarded root's closure reaches `build_meta_bytes`
