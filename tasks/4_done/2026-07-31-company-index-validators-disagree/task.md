# Three company-key validators disagree, and the coverage report is the most optimistic

- **Priority**: P2 (someday)
- **Area**: harness
- **Source**: adversarial review of workspace phase 7, 2026-07-30 — all reproduced
- **Claimed-by**: agent (fix/07-company-key-validators-agree), 2026-07-31

## Goal

Make `validate_meta`, the reconciler's `company-index` check, and `status.py --company-keys` agree
on what a valid `company_key` is, and close the linter holes that let a broken index pass.

## Context

Phase 7 landed three independent validators. A review drove real values through all three and they
disagree — and the one that disagrees most optimistically is the phase's own
definition-of-done command.

### 1. Trailing newline: accepted, rejected, and invisible

`KEY_RE` / `_COMPANY_KEY_RE` end in `$`, which matches before a trailing newline.

| `company_key` value | `validate_meta` | reconciler | `--company-keys --strict` |
|---|---|---|---|
| `"acme-labs\n"` | accepted | FINDING | counted keyed **and** resolved, exit 0 |

`company_index.KEY_RE.match("acme\n")` is also True, so a key containing a newline can enter the
index and then become a directory name. Use `\Z`, and make the reconciler and `status.py` agree on
whether they strip.

### 2. Falsy keys are hard errors that the coverage report cannot see

| value | `validate_meta` | reconciler | `--company-keys --strict` |
|---|---|---|---|
| `""` | ERROR | FINDING | counted **unkeyed**, exit 0 |
| `false` | ERROR | FINDING | counted **unkeyed**, exit 0 |
| `0` | ERROR | FINDING | counted **unkeyed**, exit 0 |

Cause: `status.py` does `str(info.get("company_key") or "").strip()`, and `load_application` drops
falsy values. So `--company-keys --strict` gives a clean bill of health for a tree the other two
validators both call broken. An unkeyed application and a *malformed* one must not report the same.

### 3. The linter holes

All reproduced against a lint-clean index:

- **A duplicate top-level key is silently last-wins** and `lint()` says nothing — one employer is
  deleted and the other inherits its key. This is the same PyYAML trap the "keys must be `str`" rule
  exists for, and `review_gate._LedgerLoader` — cited in the module docstring as the precedent for
  exactly this class of problem — sits 30 lines from the code that reads the file and is not reused.
- **Display↔display and key↔display collisions are not linted**, so `resolve()` is decided by file
  order on a lint-clean index. This contradicts `lookup_table`'s own docstring ("Collisions are a
  lint finding, so a linted index builds a total function"). Two displays differing only by NBSP or
  by surrounding whitespace also pass. The alias-vs-display case *is* caught; these are not.
  (The real index is clean today — latent, not live.)
- **A directory or dangling symlink at `_index.yaml` makes the reconciler no-op**: `is_file()` is
  False so the check returns clean while applications carry keys. The `chmod 000` case correctly
  reports `unreadable`; a not-a-regular-file should too.
- **An empty file is silently an empty index** — `yaml.safe_load("")` is `None`, `lint(None)` is
  `[]`, `load()` is `{}`, and `--company-keys` reports 0 keys without saying the index was empty.

### 4. The armed leak detector reports "(none)" on a structurally broken index

`review_gate.company_display_names` returns `None` — the honest `NOT INSPECTED` banner — only for
absent, unparseable, or non-dict. An empty mapping, entries that are not mappings, or entries whose
`display` field is missing all yield `[]`, which `company_hints` reports as *inspected, (none)*: a
clean bill of health from a detector that found nothing to look at. `company_index.lint` would flag
the latter two, but only on the maintainer's machine via the reconciler — the gate never consults
the linter. This is precisely the failure the `None` return is documented to prevent.

### 5. The stop-list test is a tautology

`test_stop_list_holds_no_vocabulary_new_to_this_repo` scans `automation/**` and `skills/**` for each
token — a corpus that includes the two files holding the list itself. Every token is trivially
present, so the test cannot fail. It is the named guard for the design's most load-bearing leak
argument. Scan the merge base, or exclude the two files that carry the list.

**The claim itself is true** — independently verified at `main`: all 152 tokens already occurred in
the tree under the detector's own substring matching, and this branch newly subtracted **0 of 265**
names. So no employer was blinded. The test just does not prove it.

## Definition of done

- [x] The three validators agree on trailing whitespace, `""`, `false`, `0`, and absent
- [x] `--company-keys` distinguishes unkeyed from malformed, and `--strict` fails on malformed
- [x] Duplicate top-level keys are a lint finding (reuse the ledger loader's approach)
- [x] Display↔display and key↔display collisions are lint findings; `resolve()` is total on a
      lint-clean index, as its docstring already claims
- [x] Not-a-regular-file at the index path is a finding, not a no-op
- [x] The detector reports NOT INSPECTED rather than "(none)" when it found nothing to inspect
- [x] The stop-list test can fail
