# Worklog — 2026-07-31-handoff-scaffold-omits-company-key

## 2026-07-31 — session 1 (agent, PR 09)

- Claimed from `0_backlog`, implemented, moved to `3_in-review`.
- **The design choice took most of the time, not the edit.** Three shapes were on the table;
  the one that reads best on a first pass — resolve the key when the overlay happens to be
  mounted — is the one that was rejected. Three arguments against it, in order of weight:
  the scaffolded bytes would depend on the environment; `handoff.py` holds four of the additive
  guard's roots, and a `company_index.resolve(...)` call from a match path spells no literal the
  textual guard looks for; and it needs `company_index` vendored into job-search, reversing the
  explicit ONE-copy note in `sync_vendored.py`. What tipped it was cost/benefit: with 208
  distinct keys across 243 applications, most new applications are at an employer the index does
  not carry yet, so resolution would pre-fill a minority of cases and remove no step from the
  owner's workflow.
- Implemented shape 2: `company_key: null` always, plus one stderr line per folder. `null` needed
  no new semantics — `validate_meta` accepts it, the reconciler skips it, `--company-keys` counts
  it unkeyed, and each already has a test saying so.
- Surprise: this contradicts a line in `docs/handbook/application-folders.md` ("Omit the field
  entirely when no key is assigned"). Reversed it there and in the tracker's `SKILL.md` schema
  example in the same commit, rather than leaving the docs describing the old scaffold.
- The guard needed no carve-out. `build_meta_bytes` is not in any guarded root's closure, and
  because it spells the literal out, a future edit that DOES put it there turns the existing
  guard red on its own.
- Next: none. The follow-on question — whether a `status.py` subcommand should key the unkeyed in
  bulk — was considered and deliberately not filed: assigning a key is owner judgement and the
  repair is a one-line edit, so another writer would be machinery without a job.
