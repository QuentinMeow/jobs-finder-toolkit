# The public-change review gate

The mechanical half of the defense. A test that fails whenever the public tree has changed
without a recorded review, so the diff is put in front of a reviewer at the moment it matters.

**What it is not.** It does not prove anyone read anything, and it does not detect personal
data on its own. Its job is to make an unreviewed public change *impossible to miss*, and to
leave a tracked trace of who reviewed what. An agent determined to rubber-stamp it can.

## Files

```text
automation/publish/
├── review_gate.py          # the check; importable and runnable
├── review_ledger.yaml      # the tracked acknowledgment log
└── tests/test_review_gate.py
```

All three live in the **public** repo, because the thing being reviewed is public content and
the gate must run in the public repo's CI where `--no-verify` cannot reach it. Since the
public repo is also the working root, the gate runs in-place — no cross-repo git calls.

## How it decides

1. Read the last acknowledged commit from `review_ledger.yaml` — the last row whose commit
   is an **ancestor of HEAD** (see "The rebase case" below).
2. `git log <last-ack>..HEAD` over the tracked public tree, **excluding `review_ledger.yaml`
   itself** — otherwise acknowledging a change is itself a change and the gate never
   converges.
3. If that range is empty → pass.
4. If not → **fail**, printing the commit list, the changed files, and the instruction.

Verified against this repo: the range query, the file list, and a stable recomputable digest
all work.

```console
$ git diff <last-ack>..HEAD -- . ':!automation/publish/review_ledger.yaml' | shasum -a 256
3283d8cfff9c461f…     # identical on re-run
```

## The rebase case: a row can name a commit that never lands

A row is acknowledged against a **branch tip**, and a branch tip is not a stable name. This
is a design fact, not an implementation detail: **acknowledging a tip before the merge means
the row names a SHA that a stack update will rewrite.** Merging a stack bottom-up updates each
PR above onto its newly merged base, and that rebase gives every commit a new SHA. The row is
honest — the review happened — but the commit it names is not in the trunk's history.

Observed on this repo, 2026-07-29: PRs #90, #91 and #92 were a stack, and after the bottom-up
merge four ledger rows named commits that are real, were genuinely reviewed, and are not
ancestors of `main`. Each had a patch-equivalent twin that did land.

The rule that follows: **a row whose commit is not an ancestor of HEAD describes a change that
is not in this history, so it cannot contribute to the chain.** A diff from it would cover a
change nobody made. Concretely:

- The chain is built from the **ancestor rows alone**. A row's range runs from the most recent
  *preceding ancestor row*'s commit to its own; a row with no preceding ancestor row opens the
  chain with a zero-width range, which is what the seed row already is.
- Off-chain rows are **skipped for digest verification, counted, and reported by name**. They
  are never dropped — an append-only ledger whose orphaned rows vanished from the report would
  be hiding exactly the reviews that were hardest to place.
- The base for an unreviewed diff is the **closest surviving ancestor row**, so the `git diff`
  command and the digest the gate prints are copy-pasteable in the checkout the reader is in.
- The hard `the ledger is out of sync with this branch` error now fires only when **no row at
  all** is an ancestor — the genuine "this ledger describes another repository" case.

Two ways a row falls off the chain, and the report distinguishes them because they mean
different things to whoever is reading:

| Status | What it means | What the reader can still do |
|---|---|---|
| `EXISTS here but is NOT an ancestor of HEAD` | The commit is in this object store, on another line of history | `git show` it; the row's diff can still be inspected locally |
| `UNKNOWN OBJECT — not in this checkout at all` | Not a known object here | Nothing local. A clone carries only **reachable** objects, so once the branch is deleted the commit is gone in CI while the author's repo still has it |

That second row is why a recovery may never require diffing *from* an orphaned commit: on CI
the object does not exist. The reconciliation row is written on the trunk, from the closest
surviving ancestor row, and its `finding:` records the rewrite.

```yaml
# The four rows above name commits rebased away by the stack merge. Left in place
# (append-only); this row acknowledges the surviving range from the last ancestor row.
- commit: 22a11443
  reviewed_by: agent
  date: 2026-07-29
  files: 33
  digest: sha256:1923f962537b1404
  finding: >-
    No new content. This range is 1db7622f..HEAD — exactly what PRs #90-#92 carried,
    each already reviewed on its own branch before the rebase renamed it. …
```

## The failure message

The wording matters — this is an instruction, not a bug report, and it is read by an agent.

```
PUBLIC REVIEW GATE — not a test failure. Action required.

7 commits have changed the published tree since the last recorded review
(070324a0 → 9e3bec37), touching 14 files:

    AGENTS.md
    automation/publish/check_public.py
    handbook/private-overlay.md
    ...

These files ship to a public repository. Read the diff and confirm none of it
contains a real name, employer, school, date, salary, or anything about the
owner's actual job hunt.

    git diff 070324a0..9e3bec37 -- . ':!automation/publish/review_ledger.yaml'

Hint — names newly introduced by this diff that match a company in the private
tree (advisory only, see below):  (none)

Then append to automation/publish/review_ledger.yaml:

    - commit: 9e3bec37
      reviewed_by: agent          # or: human
      date: 2026-07-28
      files: 14
      digest: sha256:3283d8cfff9c461f
      finding: none               # or a description of what you found and fixed
```

## The ledger

```yaml
# Every commit touching the published tree is reviewed for personal data before it
# ships. Append-only. `digest` is recomputed by the gate, so a row cannot be written
# without fetching the real diff.
- commit: 9e3bec37
  reviewed_by: agent
  date: 2026-07-28
  files: 14
  digest: sha256:3283d8cfff9c461f
  finding: none
```

The gate recomputes `digest` from the range the row claims and fails if it disagrees. That
does not prove reading — it forecloses guessing, and it forces the diff into the reviewer's
context, which is where the judgment actually happens.

**Design choices worth stating:**

- **Append-only.** History of who reviewed what is the point; rewriting a row is a finding.
- **A row per commit range, not per file.** Per-file attestation was considered and rejected:
  at 14 files a change it turns review into transcription, and volume is how a checklist
  becomes a rubber stamp.
- **`finding:` is required and free-text.** A row that says `none` on a diff that later turns
  out to leak is evidence about the reviewer, which is the only accountability a gate like
  this can offer.
- **Seeded, not retroactive.** On introduction the ledger records the current HEAD; the gate
  does not demand a review of history.

## The advisory detector

The `Hint —` line above comes from a narrowed cross-reference. I prototyped the obvious
version and it is unusable as anything stronger:

> Flagging any public file that names a company present in the private tree matched **51 of
> 177** private company tokens across the current public tree — led by `canonical` (114
> files), `writer` (103), `render` (85), `lambda` (59), `customer`, `iterable` — ordinary
> English words — plus Google, Microsoft, Amazon and Anthropic, which appear legitimately as
> ATS providers and model vendors.

So it is narrowed on four axes and remains advisory:

1. Runs on the **diff**, not the tree.
2. Subtracts every token already present in the public tree *before* the change — a name
   that was already there is not news.
3. Matches **display names** from `companies/_index.yaml`, not slug fragments, so `canonical`
   only fires as `<Name> Ltd.` and `lambda` only as `<Name> Labs`.
4. Skips `examples/` and the ATS registry, which are supposed to name companies.

It prints hints. It never fails the gate by itself. If it goes quiet for a month it is
probably mistuned, and that is a task, not a crisis.

## Where it runs

| Surface | Behaviour |
|---|---|
| `pre-commit` | Runs alongside the leak guard. Fast — one `git log`, one `git diff` |
| CI | Same check; this is the one `--no-verify` cannot skip |
| On demand | `.venv/bin/python automation/publish/review_gate.py` |
| A contributor without the overlay | Gate runs; the advisory detector reports "not inspected" rather than silently passing |

## Decided (2026-07-29): what counts as "the public tree"

**Everything tracked except the ledger**, per the recommendation below. Also decided: one row
may cover a range of commits, and an agent may sign its own review (`reviewed_by: agent`) — a
human row is required only when the advisory detector fires. Implemented in
`automation/publish/review_gate.py`; the reasoning below is kept as the record.

Two implementation facts the scoping made necessary:

- **The decision is on the FILE LIST, not the commit list.** A commit that touches only the
  ledger still appears in `git log`, so "is the commit range empty" would never converge. The
  gate decides on `git diff --name-only <last-ack>..HEAD -- . ':!<ledger>'` being empty, and
  the digest uses the same exclusion.
- **The workflow has a one-commit lag.** At `pre-commit` time HEAD is the *previous* commit, so
  the ledger is read from the **working tree**: you stage the row for HEAD alongside your next
  change and commit once (one row per commit, always one behind). A ledger-only commit changes
  no watched file, which is how a branch is closed green before a push — CI evaluates the tip.

## Open (resolved above): what counts as "the public tree"

Two scopings, with a real ergonomic difference at ~5–20 toolkit commits a day:

- **Everything tracked except the ledger** (recommended). Simplest rule, no gaps. But every
  toolkit commit needs a review row, including ones touching only `tasks/` or `memory/`.
- **Only paths in the exporter allowlist.** Fewer rows — but it excludes `memory/`, `tasks/`,
  `message-queue/`, and `history/`, which is exactly where an agent writes prose about real
  work. The four live examples of employer names in the public tree are all in that excluded
  set.

Recommended: everything. If the row rate becomes painful, the right relief is batching
(one row may cover a range of commits) rather than narrowing the scope.

## What it does not do

- It does not inspect the working tree, only commits. An uncommitted public edit is invisible
  until it lands.
- It does not read `git stash`, reflogs, or any other repo.
- It cannot tell a reviewed row from a fabricated one beyond the digest.

## Human questions / additional tasks

<!-- Free space. -->
