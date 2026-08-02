# Five broken references inside the private overlay, and no gate can see them

- **Priority**: P2 (someday)
- **Area**: repo
- **Source**: 2026-08-02 session fixing commands that fail on a healthy repo — found while
  making `automation/gates/run_gates.py` stop judging the overlay (commit "fix(gates): stop
  run_gates judging the private overlay's links")
- **Claimed-by**:

## Goal

The overlay's own markdown carries 5 broken references. Fix them in the overlay repo, and
decide whether anything should keep watching for the next five — because after this session
nothing does automatically.

## Context

`automation/gardener/verify_links.py` reads the private overlay's tracked `.md` files whenever
`private/` is mounted, and reports 5 broken references there. They are real: the targets do not
resolve.

Nothing enforces them, and that is deliberate on both sides:

- `automation/hooks/pre-commit` passes `--no-overlay`, in a comment that explains why — the
  overlay is a SEPARATE git repository at its own commit, so judging this branch's documents
  against whatever the overlay happens to be checked out at compares two unrelated states, and
  "the branch becomes uncommittable on the maintainer's own machine".
- CI has no overlay at all, so the flag is a no-op there.
- `automation/gates/run_gates.py`'s `verify-links` gate did NOT pass it, which is why the
  repo's own "run every gate" command exited 1 on a green tree in any maintainer checkout.
  That gate now passes `--no-overlay` too, matching what the hook and CI actually enforce —
  which is what leaves these 5 with no automatic watcher.

The one routine that still reads them is the deliberate, run-by-hand gardener one:
`automation/gardener/gardener.py --all` therefore also exits 1 for exactly this reason, and
that is BY DESIGN — `--all` runs `verify-links` last "so its exit code is the overall gate",
and the hook's comment names the gardener as where overlay coverage belongs. It is a report,
not a blocking gate; it does not run in pre-commit or CI. Do not "fix" that exit code by
teaching the gardener to skip the overlay — that would delete the only coverage there is.

**The 5 paths are not named here on purpose.** This is a tracked file in the PUBLIC tree, and
overlay paths describe the private tree's shape. `verify_links.py`'s own docstring carries the
same warning: with the overlay mounted its report names `private/` paths, and that output must
never be pasted into public text. Reproduce them instead:

```bash
# From a maintainer checkout with private/ mounted. Read the exit code, never a pipe.
.venv/bin/python automation/gardener/verify_links.py > local/scratch/overlay-links.log 2>&1
echo "EXIT=$?"      # 1 as of 2026-08-02
```

The failing block is headed `BROKEN references: 5`, immediately above the
`references: N broken of …` summary line. As of 2026-08-02: 5 broken of 3789 verified with the
overlay mounted; `--no-overlay` is 0 broken of 3134 verified, exit 0.

Repairs belong in the overlay repository, not here. If a watcher is wanted, the candidate is
the overlay's own pre-commit hook (it can judge its own documents against its own commit
without the cross-repo mismatch) — but that is a design choice, not a mechanical repair, which
is why this is a task and not a `message-queue/needs-agent/retries/` item.

## Definition of done

- [ ] `.venv/bin/python automation/gardener/verify_links.py` exits 0 in a maintainer checkout
      with `private/` mounted (currently 1).
- [ ] `.venv/bin/python automation/gardener/gardener.py --all` exits 0 there for the same
      reason (it is the same routine; no change to the gardener is expected or wanted).
- [ ] A recorded decision on whether the overlay gets its own link watcher, or whether the
      run-by-hand gardener routine stays the only one — either outcome written down, in the
      overlay if it names overlay paths.
