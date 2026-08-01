# The store can detect a corrupt blob but has no way to repair one

- **Priority**: P2 (someday)
- **Area**: harness
- **Source**: adversarial audit #2, findings 19 (verify-on-dedupe) and 21 (nothing
  sweeps `_blobs`); both triaged as ACCEPTED (not fixed) by the branch that
  cleared the audit's tail, with the reasons recorded in
  `automation/shared/store/blobs.py` (`write` and `present_shas` docstrings)

- **Claimed-by**: <(set when work starts, before the first change)>

## Goal

An owner who is told a blob is `corrupt`, or who has crash debris in `_blobs`,
has one documented command that fixes it.

## Context

Two residues the audit found, both real, neither fixed:

1. **`BlobStore.write` never heals.** It dedupes on `path.exists()` alone, so a
   re-capture holding the correct bytes in memory declines to repair a corrupted
   file and returns a `BlobRef` implying success. Verifying on every duplicate
   write is a full read+decompress on the capture hot path, where duplicates are
   the common case (a re-sync re-presents every payload), so the check does not
   belong there. `corrupt` is already a LOUD state — `state()`, `validate_store`
   and `store_show` all report it — so nothing is silent today; what is missing is
   the repair.
2. **Nothing sweeps `_blobs`.** A SIGKILL mid-`atomic_write_bytes` leaves a
   `.tmp-<rand>.zst` in the shard forever: `find_debris_dirs` is deliberately
   scoped to `raw/<source>/` and explicitly excludes `_blobs`. The phantom
   empty-sha it used to produce in `present_shas` IS fixed (that was a wrong
   answer, not just untidy); the file itself is left alone, because adding an
   unattended delete path into `_blobs` is exactly the class of change the store
   just spent a PR hardening against, and it would need its own age and ownership
   rules to be safe.

The natural home is a `--repair` mode on `automation/store/gc_store.py`, or a
sibling tool: opt-in, dry-run by default like every other store path, reporting
what it would touch before it touches it.

## Definition of done

- [ ] An explicit, dry-run-by-default operator command that (a) re-writes a blob
      whose bytes are available and whose file fails verify, and (b) removes
      `_blobs` temp files older than a stated window
- [ ] Neither behaviour is reachable from the capture path
- [ ] Tests: a corrupt blob is healed only under the explicit command; a fresh
      `.tmp-*` file is NOT removed; the crash-window `pruned-pending` state is
      untouched
- [ ] `automation/vendoring/sync_vendored.py --check` clean
