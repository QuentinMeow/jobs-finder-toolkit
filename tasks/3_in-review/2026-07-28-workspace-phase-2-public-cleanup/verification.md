# Verification — 2026-07-28-workspace-phase-2-public-cleanup

Commands actually run on 2026-07-29 against the phase-2 stack's tip (`fc0180b`) and their real
output. Output is pasted inline rather than cited: the handbook's scratch rule forbids a durable
record from pointing at a path under `local/` as its evidence, and everything below was produced
in throwaway working directories that will not exist tomorrow.

Two proofs compare a "before" tree. Those were produced from git itself — `git archive` or
`git worktree add` at the commit named — so they are reproducible from this repo alone.

## The full gate — 20 steps, all green

The gate script mirrors `.github/workflows/ci.yml` plus the execution plan's gate command:
vendor drift, byte-compile, reconciler with `--require-roots`, leak guard, review gate
`--verify-all`, instruction budget `--strict`, link/symlink/drift verification, mail safety, nine
unit suites, the filter-variant check, and a strict export dry-run.

```
$ zsh gate.sh          # GARDENER_PATH=automation/gardener
===== gates =====
PASS  vendor-drift
PASS  byte-compile
PASS  reconcile
PASS  leak-guard
PASS  review-gate
PASS  instruction-budget
PASS  verify-links
PASS  mail-safety
===== unit suites =====
PASS  tests:reconcile
PASS  tests:gardener
PASS  tests:hooks
PASS  tests:shared
PASS  tests:publish
PASS  tests:store-example
PASS  tests:resume-writer
PASS  tests:job-search
PASS  filter-variants
PASS  tests:app-tracker
PASS  tests:github-wf
===== export dry-run =====
PASS  export-strict

ALL GREEN
```

## The planted-defect proofs

A green run is not evidence that a moved check still checks anything. Each of the three checks
whose constants named a moved root was re-armed against a deliberately planted defect.

### `verify_links.py` still fails on a broken ref at the new root

A genuinely broken backticked reference was appended to `docs/handbook/file-organization.md`,
then reverted.

```
$ printf '\nSee `docs/handbook/definitely-not-a-real-file.md` for details.\n' \
    >> docs/handbook/file-organization.md
$ .venv/bin/python automation/gardener/verify_links.py; echo "exit=$?"
  BROKEN references: 1
    docs/handbook/file-organization.md:78  ->  docs/handbook/definitely-not-a-real-file.md
  FAIL: broken references / symlinks / drift found.
exit=1
```

### …and the same ref at the retired root name is invisible

This is the finding, not a passing test. The identical broken reference, spelled with the root
name phase 2 retired, produces a clean run — it is not reported broken, not reported advisory,
and not counted in any skip tally.

```
$ printf '\nSee `handbook/definitely-not-a-real-file.md` for details.\n' \
    >> docs/handbook/file-organization.md
$ .venv/bin/python automation/gardener/verify_links.py; echo "exit=$?"
  references: all resolve
  OK: links, symlinks, and vendored copies verified.
exit=0
```

The cause is `check_references()` at `automation/gardener/verify_links.py:249-252`: a token that
resolved under no base is only recorded when it starts with an absent strict root or a present
one. Anything else falls out of the loop. 76 references at the four retired root names survive
across 24 record files and are now in that hole. Filed as
[`2026-07-29-verify-links-misses-markdown-and-nonstrict-roots`](../../0_backlog/2026-07-29-verify-links-misses-markdown-and-nonstrict-roots/task.md).

### `--require-roots` still fails when `docs/roadmap/` is absent

Run against a `git archive` of the tip extracted to a scratch directory, so the real tree was
never touched. `reconcile.py` resolves `REPO_ROOT` as `parents[2]` of its own file, so the copy
is a self-contained repo for this purpose.

```
$ python <copy>/automation/reconcile/reconcile.py --check --require-roots      # control
reconcile: OK (8 checks clean)
exit=0

$ mv <copy>/docs/roadmap <copy>/docs/roadmap-MOVED
$ python <copy>/automation/reconcile/reconcile.py --check --require-roots
reconcile: 1 finding(s)
  [require-roots] docs/roadmap: missing — roadmap-fresh would silently no-op (plain --check tolerates this by design; --require-roots does not)
exit=1

$ python <copy>/automation/reconcile/reconcile.py --check                      # same tree
reconcile: OK (7 checks clean)
exit=0
```

The last run is the silent disarm made visible: plain `--check` is green, and the only signal
that a check stopped running is the count dropping from 8 to 7.

### `roadmap-fresh` still fails on a stale roadmap

```
$ grep -v 'Last-updated' <copy>/docs/roadmap/current-state.md > x && mv x <copy>/docs/roadmap/current-state.md
$ python <copy>/automation/reconcile/reconcile.py --check --require-roots
reconcile: 1 finding(s)
  [roadmap-fresh] docs/roadmap/current-state.md: missing a Last-updated line
exit=1
```

## The canary census, before and after

There is no shipped consumer that globs canary sets, so a stand-in was written that discovers
them the way a consumer would — both layouts, so one script runs on both trees — parses each
file, and exits non-zero if it finds fewer than nine sets. "Before" is a `git archive` of
`1441f42`, the tip of the PR that precedes the evals move.

```
$ python canary_census.py <archive of 1441f42>
application-tracker          evals/application-tracker/canaries.yaml   6 canaries
ask-me-anything              evals/ask-me-anything/canaries.yaml       4 canaries
behavioral-interview-prep    evals/behavioral-interview-prep/canaries.yaml  5 canaries
company-research             evals/company-research/canaries.yaml      6 canaries
email-assistant              evals/email-assistant/canaries.yaml       8 canaries
github-workflow              evals/github-workflow/canaries.yaml       4 canaries
interview-calendar           evals/interview-calendar/canaries.yaml    4 canaries
job-search                   evals/job-search/canaries.yaml            5 canaries
resume-writer                evals/resume-writer/canaries.yaml         8 canaries
--
9 canary sets, 50 canaries, 0 malformed
exit=0

$ python canary_census.py .
application-tracker          evals/canaries/application-tracker.yaml   6 canaries
ask-me-anything              evals/canaries/ask-me-anything.yaml       4 canaries
behavioral-interview-prep    evals/canaries/behavioral-interview-prep.yaml  5 canaries
company-research             evals/canaries/company-research.yaml      6 canaries
email-assistant              evals/canaries/email-assistant.yaml       8 canaries
github-workflow              evals/canaries/github-workflow.yaml       4 canaries
interview-calendar           evals/canaries/interview-calendar.yaml    4 canaries
job-search                   evals/canaries/job-search.yaml            5 canaries
resume-writer                evals/canaries/resume-writer.yaml         8 canaries
--
9 canary sets, 50 canaries, 0 malformed
exit=0
```

Same count is not the same content, so every blob was hashed across the move as well:

```
$ for s in <the nine skills>; do
    a=$(git cat-file blob 1441f42:evals/$s/canaries.yaml       | shasum -a 256 | cut -d' ' -f1)
    b=$(git cat-file blob cf2eb45:evals/canaries/$s.yaml       | shasum -a 256 | cut -d' ' -f1)
    [ "$a" = "$b" ] && echo "IDENTICAL  $s" || echo "DIFFER  $s"
  done
IDENTICAL  application-tracker
IDENTICAL  ask-me-anything
IDENTICAL  behavioral-interview-prep
IDENTICAL  company-research
IDENTICAL  email-assistant
IDENTICAL  github-workflow
IDENTICAL  interview-calendar
IDENTICAL  job-search
IDENTICAL  resume-writer
```

Against the stack tip rather than `cf2eb45`, `email-assistant` differs by one line: the next PR's
scratch-root rename changed a negative assertion from `tmp/email-assistant/` to
`local/email-assistant/`. That is the only canary byte that changed in the whole phase.

## `tmp/` → `local/` moved everything and dropped nothing

The scratch tree is untracked, so git cannot testify here. The pre-rename listing was captured
before the `mv`; the post-rename listing was re-taken today with the same command and collation.

```
$ (cd local && find . -type f | sed 's|^\./||' | LC_ALL=C sort) > after.txt
$ wc -l before.txt after.txt
     102 before.txt
     102 after.txt
$ shasum -a 256 before.txt after.txt
550ca6eef70a73c8a32fa0b7841ecb67a94887a337c96a108a15503259a74eff  before.txt
550ca6eef70a73c8a32fa0b7841ecb67a94887a337c96a108a15503259a74eff  after.txt
$ diff before.txt after.txt && echo "PATH SETS IDENTICAL"
PATH SETS IDENTICAL
$ du -sh local
1.2G	local
$ ls -d tmp
ls: tmp: No such file or directory
$ grep -n '^local/' .gitignore
6:local/
```

The listing itself is not pasted: it contains application folder names carrying real employers,
which is exactly the material the review item in the overlay's queue is about. The two hashes
are over identical byte streams, which is the claim that matters — 102 paths in, 102 identical
paths out, zero renames within the tree. The `1.2G` figure is measured after the rename only;
no before-size was recorded, and a same-filesystem directory rename cannot change content.

## The `docs/designs/` contract shim is still a symlink

`export_public.py` deliberately *follows* this link so the export ships real content, which means
replacing it with a regular file would look identical in the exported tree and only show up when
Claude Code stopped loading the folder's contract.

```
$ git ls-files -s docs/designs/CLAUDE.md
120000 47dc3e3d863cfb5727b87d785d09abf9743c0a72 0	docs/designs/CLAUDE.md
```

## The published file set did not change

The consolidation moved 135 files, and none of them changed what gets published.

```
$ python <worktree at ac4c43b>/automation/publish/export_public.py --dest <a> --strict --force
OK: no public-repo leaks detected. Safe to publish.
Leak guard PASSED.
$ find <a> -type f -not -path '*/.git/*' | wc -l
     566

$ .venv/bin/python automation/publish/export_public.py --dest <b> --strict --force
OK: no public-repo leaks detected. Safe to publish.
Leak guard PASSED.
$ find <b> -type f -not -path '*/.git/*' | wc -l
     566
```

## Every gardener routine runs from its new home

```
$ .venv/bin/python automation/gardener/gardener.py --all; echo "exit=$?"
gardener · self-measure [DRY-RUN]
gardener · expire-discoveries [DRY-RUN]
gardener · compact-logs [DRY-RUN]
gardener · lessons-report (report-only) [DRY-RUN]
gardener · card-staleness (report-only) [DRY-RUN]
gardener · skill-drift (report-only) [DRY-RUN]
gardener · store-report [DRY-RUN]
gardener · verify-links (report-only) [DRY-RUN]
gardener --all complete (dry-run). Run an individual routine with --apply to act.
exit=0
```

All eight dispatch and complete. `store-report` reports three pre-existing schema findings in the
private overlay's email index (missing header properties in a built index) — unrelated to this
phase, present before it, and read-only either way.

`REPO_ROOT` resolves correctly from the new depths, which is the thing the depth-constant
conversion had to get right:

```
$ .venv/bin/python -c "import sys; sys.path.insert(0,'automation/gardener'); import _common; print(_common.REPO_ROOT)"
<the repo root>
$ .venv/bin/python -c "import sys; sys.path.insert(0,'automation/company-levels'); import import_company_levels as m; print(m.REPO_ROOT)"
<the repo root>
```

(Both printed the checkout's absolute path, redacted here — the leak guard rejects a home path in
a tracked file, which is itself a working proof that the staged-index guard from phase 0 is on.)

`automation/search-recall-audit/audit.py --help` dispatches its three subcommands and exits 0.
`store_refilter.py` raises `NameError: name 'prof_label' is not defined` on its final print; the
same line is broken at `d9aa3cb`, before this phase began, so it is pre-existing and is now on
the execution plan's opportunistic-repair list.

## The markdown-link count, which no gate can see

`verify_links.py` checks backticked refs only. A throwaway checker was written to resolve every
relative `[text](path)` target in every tracked `.md`.

```
$ python mdlinks.py <worktree at d9aa3cb>      # this stack's base
TOTAL BROKEN RELATIVE LINKS: 36
$ python mdlinks.py .                          # this stack's tip
TOTAL BROKEN RELATIVE LINKS: 31
```

The count fell, but the two sets share **not one entry**: 36 pre-existing breaks were repaired
(seven design docs citing a `../STYLE.md` that has never existed, plus `PRIVATE_OVERLAY.md` and
`../ARCHITECTURE.md` — the last resolving on macOS only through case-insensitivity, so it would
have failed on Linux CI) and 31 new ones appeared, almost all `design/` → `docs/designs/` misses
in dated records and task files. The record PR repairs the ten it can justify repairing — seven
in the execution plan and three in this task file — and files the rest.
