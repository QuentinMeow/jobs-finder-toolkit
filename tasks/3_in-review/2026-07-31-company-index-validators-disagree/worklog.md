# Worklog — 2026-07-31-company-index-validators-disagree

## 2026-07-31 — session 1 (agent)

- Branch `fix/07-company-key-validators-agree`, seventh of the stack, based on
  `fix/06-company-key-guard-transitive`. Never rebased.
- All seven definition-of-done boxes closed, each with a test that fails on the base
  source and passes on this one. Transcripts in `verification.md`.
- Two commits changed the published tree, split by layer: the shared module + its
  vendored copies first, then the three consumers (reconciler, coverage report,
  detector) plus the handbook line. Ledger rows follow the one-behind rule; a
  ledger-only commit closes the branch.

**What was harder than it looked.** Three of the seven fixes needed a decision, not
just a patch:

- *Where duplicates are detected.* By the time `lint()` sees a mapping, PyYAML has
  already thrown the loser away, so no post-hoc check can work. `_IndexLoader`
  records duplicates while parsing and they ride on a `RawIndex` (a `dict`
  subclass), which keeps `lint()`'s one-argument signature — the reconciler adapter
  depends on it. Only HALF of `review_gate._LedgerLoader`'s approach transfers: the
  ledger loader turns implicit typing OFF, and this one must leave it ON so the
  "keys must be str" rule can still SEE the YAML 1.1 boolean an unquoted `on:` key
  becomes.
- *How `--company-keys` reads the key.* `load_application` drops falsy fields by
  design and other callers depend on that, so the fix reads the raw value straight
  out of `meta.yaml` in a small local helper rather than changing the shared loader.
- *Empty vs absent.* `read_raw` now returns `{}` only for a genuinely absent file
  and `None` for a present-but-empty one, which is what makes the empty-file finding
  possible without turning "no overlay mounted" red. `{}` written in the file still
  means an index with no entries.

**The stop-list test.** The defect was in the test, not the source, so the
before/after had to be run as the same poison against the two test files: a nonce
token added to `ALIAS_STOP_LIST` leaves the base guard GREEN and turns the new one
RED. The claim the guard defends was re-measured against the narrowed corpus and is
unchanged — 0 of 152 tokens are new to it, so no token had to be removed.

**Blast radius.** The owner's real index lints clean under every new rule (222
entries, 0 duplicates, 0 findings) and `--company-keys --strict` exits 0 over 243
applications (243 keyed, 0 malformed, 0 unresolved). No new rule fired, so nothing
needed fixing and no decision needed filing.

**Eval gate.** No `SKILL.md`, `LESSONS.md` or `reference.md` was edited, so
`evals/README.md`'s risk-based gate does not apply. The one documentation change is
a clause in `docs/handbook/application-folders.md` recording that a present-but-blank
`company_key` is now a `--strict` failure everywhere.

**CI shape reproduced** in a detached worktree at the branch tip with neither
`private/` nor `config.yaml` present: shared 455 OK, reconcile 40 OK, publish 156 OK
(1 skipped), application-tracker 82 OK, vendor drift in sync, reconciler 9 checks
clean, leak guard clean.

- Next: PR against `fix/06-company-key-guard-transitive`, then watch CI.
