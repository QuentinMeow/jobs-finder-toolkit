# Reconcile the re-created legacy data root into the canonical store

- **Priority**: P1 (this round)
- **Area**: repo
- **Source**: Private-overlay inventory during the 2026-08-06 person-first folder refactor
- **Claimed-by**:

## Goal

Prove which job-store rows exist only under the re-created legacy `data/` root, import their
state into the canonical `store/jobs/` model without loss or duplicate effects, identify the
writer that recreated the retired path, and make the old root safe for the owner to retire.

## Context

The original workspace migration renamed `data/` to `store/` at byte identity. A later commit
recreated the old root with newer dated index and state files that are absent from the canonical
store, while the active real config still points to `store/`. This is a live split-brain path
regression, not an archive. The private-layout refactor deliberately leaves both roots untouched;
moving or deleting the old root before semantic reconciliation could discard owner data or cause
a future writer to keep updating the wrong place.

Agents never delete owner data. The task ends by proving the canonical store is complete and
proposing owner retirement of the old root; it does not perform that retirement.

## Definition of done

- [ ] The recreating writer and configuration path are identified and fixed with a regression test.
- [ ] Unique index, state, and raw/derived dependencies are measured without exposing private rows publicly.
- [ ] A store-aware import or rebuild preserves canonical fold semantics and passes store validation.
- [ ] A before/after manifest proves no legacy byte was lost.
- [ ] The owner receives a deletion proposal only after the canonical store is verified complete.
