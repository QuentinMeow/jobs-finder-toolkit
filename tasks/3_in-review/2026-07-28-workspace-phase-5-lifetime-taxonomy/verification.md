# Verification — 2026-07-28-workspace-phase-5-lifetime-taxonomy

Two repositories, one phase. Everything below was run after the last migration commit.
Output is trimmed to the relevant lines and is otherwise verbatim. **The private tree is
described by counts and folder shapes only** — no employer, person, posting, date or
filename from it appears here.

## Nothing was lost

```
$ git -C private ls-files | wc -l
    3186          # identical to the pre-migration count
$ git -C private diff --name-status -M --find-renames=100% pre-phase-5-snapshot HEAD \
    | awk '{print $1}' | sort | uniq -c
   2 A
   2 D
   2 M
 745 R100
```

**747 tracked files changed path.** 745 are exact renames; the two that are not are
`config.benchmark.yaml` (rewritten in the same commit that moved it, because
`config.py` resolves its relative values against the config file's own directory) and
one cursor rule (edited later on the same branch). Both are still renames — `R059` and
`R093` under default similarity detection — so `git log --follow` works on all 747.

The acceptance number is **747, not the 825 the task carried**. 825 counted `history/`
(23 files, dropped from this phase) and 55 files whose paths do not change.

Root shape after the migration:

```
$ git -C private ls-files | awk -F/ '{print $1}' | sort | uniq -c | sort -rn
2361 applications      497 companies       115 evals        63 me
  51 market             23 history          16 message-queue 15 memory
  13 tasks              12 store            11 skills         6 docs
```

`interviews/`, `data/`, `job-search/`, `job-search-profiles/`, `benchmark/`, `inputs/`,
`templates/` and `cursor-rules/` are gone. `applications/<status>/<slug>/` is byte-for-byte
where it was.

## The 450 MB hazard, asserted before the commit that created it

`data/` held 12 tracked files and 83,479 ignored ones (450 MB) behind nine
`private/.gitignore` patterns, all beginning `data/`. The rename and the pattern rewrite
are **one commit**; anything in between would have un-ignored all of it, and a single
`git add -A` in that window is not recoverable.

```
   ok: 9 ignore patterns rewritten data/ -> store/
   IGNORED      store/jobs/raw/x.json                        <- .gitignore:22:store/*/raw/
   IGNORED      store/jobs/derived/x.json                    <- .gitignore:28:store/*/derived/
   IGNORED      store/email/raw/a/b.eml                      <- .gitignore:34
   IGNORED      store/email/derived/x.json                   <- .gitignore:35
   IGNORED      store/email/state/s.json                     <- .gitignore:36
   IGNORED      store/email/index/acct/messages.jsonl        <- .gitignore:37
   IGNORED      store/email/index/acct/by-application/x.json <- .gitignore:38
   IGNORED      store/email/index/acct/triage/x.json         <- .gitignore:39
   IGNORED      store/email/annotations/evidence/x.md        <- .gitignore:40
   NOT-IGNORED  store/jobs/index/postings.jsonl
   NOT-IGNORED  store/jobs/state/identifiers.yaml
   NOT-IGNORED  store/email/index/acct/header.json
   NOT-IGNORED  store/email/annotations/notes.md
   NOT-IGNORED  store/README.md
   ok: 13 pending index entries (expected 13)
```

Both halves matter. Lines 38, 39 and 40 match **zero files today**, so a rewrite that
dropped them would be invisible to any count-based check — they are asserted by pattern.
And the five NOT-IGNORED entries prove the new rules are not too broad: a `store/` rule
that swallowed the tracked zones would have silently dropped 12 tracked files.

## Every accessor resolves

19 `Path`-returning accessors, enumerated from `config.py` rather than from a list, so a
forgotten key cannot pass by being left out. All 19 resolve to something that exists.
Before this phase `companies_root()` was the one that did not.

## The checks that fail OPEN, each proven still to bite

A green run is not evidence when the failure mode is a check that stops checking.

**1 — the two search skips.** `profile_dir()` hunted for a directory *containing* a
skip-log and returned its first guess when none matched. After the move no probe holds
one, so it would have returned a log-less directory and both skips would have matched
nothing — re-drafting postings already applied to, in silence. Replaced with direct
accessor reads:

```
applications log -> …/private/market/logs/applications-log.yaml True
company search log -> …/private/market/logs/company-search-log.yaml True
already-considered: 367 urls, 369 (company, role) pairs
```

**2 — the answer bank's 33 sibling-relative story references.** All 16 real source files
validate, and **none of them was edited** — which is the evidence that keeping the leaf
directory name was the right call rather than a shortcut.

```
$ for f in <the 16 sources>; do answer_bank.py validate "$f"; done
validated 16 sources          # zero failures
```

**3 — the tailoring card's display key.** `build_tailoring_card.py` and
`card_staleness.py` each carry the literal a card records beside the story bank's
checksum. Change one and not the other and every card reads permanently stale while the
checksum and the path are both correct — a symmetric failure with no error message.

```
$ build_tailoring_card.py --force
private/me/tailoring-card.md  14819 bytes
$ grep 'story-bank/ sha256' <the card>
- `me/interviews/story-bank/` sha256:163ccb1c… (7 stories)
$ card_staleness.py
  current — card matches its recorded source hashes.

$ printf '\n<!-- planted -->\n' >> <one story file>
$ card_staleness.py
  STALE: 1 source(s) changed since the card was built:
    STALE  me/interviews/story-bank/
$ <revert the plant>
$ card_staleness.py
  current — card matches its recorded source hashes.
```

Seven stories, not zero — the card is built from the real bank at its new location.

**4 — `self_measure` recreating the folder the phase retired.** It writes
`candidate_dir()/metrics.yaml` on every `--apply`.

```
$ self_measure.py
  DRY-RUN: printed only. --apply writes …/private/market/logs/metrics.yaml.
$ ls -d private/applications/0_profile
ls: private/applications/0_profile: No such file or directory
```

**5 — the link checker's own root constants.** This is the one worth reading twice.
`--require-roots`, added in the previous PR, **refused the first commit after the
migration**:

```
  MISSING ROOTS (1) — a constant in this module names a directory that does not exist,
  which disarms the check rather than breaking it:
    benchmark/fixtures/
```

`benchmark/` had just become `evals/`. Without the flag the prefix would simply have
stopped matching, and a whole tier of documents would have quietly changed classification.

## The instruction surface

Removing `interviews/`, `private/interviews/` and `private/job-search/` from
`SKIP_PREFIXES` — none of those directories exists any more — surfaced **126 broken
references** across both trees. 100 of them were in two derived files and vanished on
regeneration; the rest were repaired.

```
$ automation/gardener/verify_links.py
  refs + markdown links checked across 1301 tracked .md files (1019 in the mounted overlay)
  references: all resolve
```

## The `config.yaml` block

`config.yaml` is git-ignored, so no PR can set it. It grows from 7 path keys to 16; the
copy-pasteable block is in the session scratchpad rather than here, because several
values are real filenames. Until it is applied, every accessor resolves to its old
location and fails with a missing path — loud, which is the failure mode chosen over
silence.

## What this phase did NOT do

- `examples/` still mirrors the old shape — phase 8, and two `examples/data` literals are
  pinned in `ci.yml` and an export test.
- `history/` did not move — filed as its own decision.
- The skip-log is still regenerated from the application folders, so deleting a rejected
  application and re-syncing still re-opens the posting. Phase 6.
- `answer_bank.py` still does not emit to `companies/<key>/derived/`; the 19
  company-prefixed files were relocated, not re-derived.
