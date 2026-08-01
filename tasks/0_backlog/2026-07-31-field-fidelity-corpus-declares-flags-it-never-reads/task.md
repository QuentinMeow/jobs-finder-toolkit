# `field_fidelity corpus` declares `--limit`/`--seed` and reads neither

- **Priority**: P2 (someday)
- **Area**: harness
- **Source**: noticed while fixing the search-recall-audit defects (adversarial audit #4), 2026-07-31

## Goal

`field_fidelity.py corpus` should either honour `--limit`/`--seed` or stop
advertising them, so the printed run is the run the caller asked for.

## Context

`automation/search-recall-audit/field_fidelity.py`'s `corpus` subparser declares
`--limit` (default 600) and `--seed` (default 42). `cmd_corpus` uses neither: it
walks every manifest and emits one row per unique posting. The module docstring
compounds it by describing `corpus` as working over "each **sampled** entity".

The behaviour is safe (it processes MORE than advertised, never less) and the
whole-store pass is cheap because blobs are deduped by sha and decompressed once.
So this is doc/CLI drift, not a correctness bug — but a flag that silently does
nothing is exactly the shape of defect this file was just cleaned of, and a caller
who passes `--limit 50` to keep a run short will not get one.

Two honest options:

* drop both flags and fix the docstring to say `corpus` is a full-store pass
  (recommended — the sampling lever belongs to `sample`, which has its own
  `--n`/`--seed` and uses them); or
* implement `--limit` as a cap on emitted rows with `--seed` shuffling the
  manifest order, and say so in the summary line.

Whichever is chosen, `skills/search-recall-audit/SKILL.md`'s field-fidelity block
shows `corpus` with no flags, so it needs no change either way.

## Definition of done

- [ ] `corpus --limit 5` either emits at most 5 rows or the flag no longer exists.
- [ ] The module docstring's description of `corpus` matches what it does.
- [ ] A test pins whichever contract is chosen.
