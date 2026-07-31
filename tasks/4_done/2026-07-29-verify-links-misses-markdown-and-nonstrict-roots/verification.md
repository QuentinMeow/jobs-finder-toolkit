# Verification — 2026-07-29-verify-links-misses-markdown-and-nonstrict-roots

Every command below was run on the branch `fix/02-verify-links-sees-markdown-and-unknown-roots`
against the maintainer checkout with the private overlay mounted. Output is trimmed to the
relevant lines and is otherwise verbatim. Overlay findings are reported by count only — the
routine prints `private/` paths and this file is tracked.

## The gate is green in both views

```
$ .venv/bin/python automation/gardener/verify_links.py
  refs + markdown links checked across 1295 tracked .md files (1019 of them in the mounted overlay)
  advisory (plans name targets that do not exist yet): 31
  permitted (dated records — rewriting them would falsify the record): 62
  references: all resolve
  skill symlinks: all resolve
  vendor drift check: OK — vendored copies in sync
  OK: links, symlinks, and vendored copies verified.
exit=0

$ .venv/bin/python automation/gardener/verify_links.py --no-overlay    # what CI sees
  refs + markdown links checked across 276 tracked .md files
  skipped refs — private/ overlay not mounted: 107
  advisory (plans name targets that do not exist yet): 20
  permitted (dated records — rewriting them would falsify the record): 53
  references: all resolve
exit=0
```

The `--no-overlay` run is the load-bearing one. Before the overlay skip class existed it
reported **3 broken**, two of them `evals/README.md:7` and `evals/protocols/ab-protocol.md:6`
linking into `private/docs/` — both reference-tier, both in `export_public.py`'s allowlist. The
first CI run after this change would have been red.

## Planted defect 1 — a broken markdown link in a reference-tier document FAILS

```
$ printf '\nSee [the thing](gone-forever.md).\n' >> docs/handbook/file-organization.md
$ .venv/bin/python automation/gardener/verify_links.py
  BROKEN references: 1
    docs/handbook/file-organization.md:77  [inline]  ->  gone-forever.md
exit=1
$ git checkout -- docs/handbook/file-organization.md
```

Before this change the same plant produced `references: all resolve`, exit 0 — the checker
read no markdown links at all.

## Planted defect 2 — the identical link in a dated record is PERMITTED, and visible

```
$ printf '\nSee [the thing](gone-forever.md).\n' >> history/conversations/2026-07-22-agentfold-restructure/handover.md
$ .venv/bin/python automation/gardener/verify_links.py
  permitted (dated records — rewriting them would falsify the record): 63
    history/conversations/2026-07-22-agentfold-restructure/handover.md:41  ->  gone-forever.md
  references: all resolve
exit=0
$ git checkout -- history/conversations/2026-07-22-agentfold-restructure/handover.md
```

Same link, same target, opposite verdict — decided by what the source document is for. The
finding is listed, which is the half that matters: a permitted break may never be silent.

## Planted defect 3 — a ref at an unrecognised root is COUNTED

```
$ printf '\nSee `handbook/definitely-not-a-real-file.md` for details.\n' >> docs/handbook/file-organization.md
$ .venv/bin/python automation/gardener/verify_links.py --list-unrecognised
  skipped refs — no recognised root prefix (…): 954, of which 232 name a file
    docs/handbook/file-organization.md:77  handbook/definitely-not-a-real-file.md
$ git checkout -- docs/handbook/file-organization.md
```

953 → 954, and the ref is named. Before this change the same plant incremented **no counter at
all** and appeared in no list — not broken, not advisory, not skipped. The paired control (the
same file spelled `docs/handbook/…`) is a hard failure, which is how we know the difference is
the root and not the file.

## `--require-roots` caught a real defect on its first run

```
$ .venv/bin/python automation/gardener/verify_links.py --require-roots
  MISSING ROOTS (1) — a constant in this module names a directory that does not exist, which
  disarms the check rather than breaking it:
    evals/fixtures/
exit=1
```

`evals/fixtures/` had been added to `RECORD_SOURCES` in anticipation of workspace phase 5
moving the benchmark fixtures there. The directory does not exist yet, so the prefix would have
matched nothing and silently protected nothing. Removed, with a comment telling phase 5 to add
it in the commit that creates the directory. After removal the flag exits 0.

## `--baseline` / `--compare` round-trip, and the leak refusal

```
$ .venv/bin/python automation/gardener/verify_links.py --baseline local/scratch/links-a.json
  baseline written: local/scratch/links-a.json
$ .venv/bin/python automation/gardener/verify_links.py --compare local/scratch/links-a.json
  compare vs local/scratch/links-a.json: resolved 0 · new 0 · unchanged 1046 · matched-loosely 0

$ .venv/bin/python automation/gardener/verify_links.py --baseline docs/links-should-refuse.json
  REFUSED to write docs/links-should-refuse.json: this baseline names 1019 overlay files, and
  that path is not git-ignored. Write it under local/ (or pass --no-overlay).
exit=1
$ ls docs/links-should-refuse.json
ls: docs/links-should-refuse.json: No such file or directory
```

Nothing was written. A baseline taken with the overlay mounted lists overlay filenames; putting
one in the tracked surface would place the owner's interview and application filenames a single
`git add -A` from the public remote.

## Repairs made

Two, both genuine, both outside the record tier:

```
docs/handbook/comparisons/resume-writing-tools.md:60
  ../architecture.md#application-folders-the-folder-is-the-status
  -> ../architecture.md#application-folders-per-job-status-folder--derived-rollup
```

and one path in the overlay's own notes still spelled with the `automation/maintenance/`
prefix that workspace phase 2 retired. That one is the proof that overlay enumeration was
worth building: it had been broken since phase 2 and no checker could see it.

## The count, and why the task's number was different

The task recorded "31–36 broken relative markdown links, no two checkers agree". Two
independent measurements — one by the design pass, one by the orchestrator — both arrive at
**23**, and agree row for row. The disagreement was never mysterious:

| extraction | broken |
|---|---:|
| no masking | 40 |
| fenced code blocks masked | 40 |
| + multi-line inline code spans masked | 25 |
| + placeholder destinations rejected | 23 |

Fenced blocks contribute **zero** false positives. All 15 documentation-example false
positives are inline code spans, and two of them wrap across a line break — which is why a
per-line stripper looks principled and removes none of the noise.

All 23 are in record-tier documents. **Nothing in a document that asserts current state was
broken**, which is why this lands green without a repair campaign.
