---
name: github-workflow
visibility: public
description: Get finished work from a local branch onto GitHub — write the PR description in this repo's human-facing Before/After format, split a long task into a stack of PRs that GitHub detects on its own, clear the gates that block a push (the pre-commit hook chain, the public review ledger, the leak guard, pre-push), and drive `gh` for CI, merges, and stack rebases. Use when the user asks to open a PR, write or rewrite a PR description, stack PRs, split work into stacked PRs, check CI, read a failing run's log, merge a stack, or rebase a stack after its base moved.
---

# GitHub Workflow — from a finished branch to a merged PR

Everything between "the work is done" and "it is on `main`": how the PR
description is written, how a stack of PRs is built (no special tool), the gates
this repo puts in front of a push, and the `gh` commands for each step.

## When to Use

- "Open a PR." · "Write / rewrite the PR description." · "Describe this branch."
- "Split this into stacked PRs." · "Stack this on top of the previous PR."
- "Is CI green?" · "Why did CI fail?" · "Merge the stack." · "Rebase the stack."
- Any push from this repo — the gates below apply whether or not a PR follows.

## 1. The PR description format

**The headline rule: a PR description opens with a section written for the human
who will use the thing, in plain English, before any technical detail.** A reader
must learn what is different for them before meeting a single file path.

Structure of that opening section:

| Part | What goes in it |
|------|-----------------|
| Heading | `## What changes for you` (the first `##` in the body — nothing above it) |
| One sub-block per distinct change | A `###` naming the change in user terms, not module terms |
| **Before.** | What happened, or what was broken, in concrete terms |
| **After.** | What happens now |
| **What you'll notice.** | The practical day-to-day effect — including friction, extra steps, or annoyance |

Writing rules:

- Short sentences. Name the actual command, file, or behaviour.
- No metaphors and no marketing words. The banned list is
  `BANNED_TERMS` in `skills/github-workflow/scripts/check_pr_body.py`
  (`--list-banned` prints it).
- **Say plainly when something gets slower, noisier, or requires manual work.
  A PR that only lists benefits is under-reported** — treat a missing downside
  as a finding against your own draft, not as good news.
- Only after that section come the technical ones: what & why, the design, how it
  was verified, what was filed (tasks, queue items, memory entries).
- This repo's `.github/pull_request_template.md` starts at `## What & why`. The
  human-facing section goes **above** it; the template's checklist stays.

### Worked example (fictional)

```markdown
## What changes for you

### Exports no longer overwrite yesterday's file

**Before.** `export.py` always wrote `out.csv`. Running it twice in one day
replaced the first run's file with no warning, and there was no way to get the
earlier one back.

**After.** It writes `out-<YYYY-MM-DD>.csv` and refuses to overwrite a file that
already exists.

**What you'll notice.** Anything that reads `out.csv` by name stops finding it —
scripts, spreadsheets, and the weekly mail job all need the new name. The export
directory now accumulates one file per day; nothing deletes them, so that is a
folder you have to clean out yourself.

### The export takes longer

**Before.** A run finished in about two seconds.

**After.** A run takes about nine seconds, because it now checksums each row
before writing so a truncated file is detected instead of shipped.

**What you'll notice.** The wait is noticeable when you run it by hand. It is
unchanged inside the nightly job, which nobody watches.

## What & why

`out.csv` was a fixed name chosen when the export ran once a week. It now runs on
demand, so the fixed name means the newest run destroys the previous one.

## Design

Date-stamping is done by the caller, not inside the writer, so the writer stays
usable for one-off paths in tests.

## Verification

`python -m unittest discover tests` — 41 tests, all pass. Ran the export twice in
one day against a scratch directory and confirmed the second run exits 1 instead
of overwriting.

## What was filed

Follow-up task for pruning old exports; no queue items.
```

### Check the body before posting it

```bash
# From a file
.venv/bin/python skills/github-workflow/scripts/check_pr_body.py local/pr-body.md
# Or from an existing PR
gh pr view <n> --json body --jq .body | \
    .venv/bin/python skills/github-workflow/scripts/check_pr_body.py
```

It checks three mechanical properties and nothing else: the first `##` heading is
the human-facing one, that section carries at least one `**Before.**` and one
`**After.**`, and no banned word appears in prose (code fences are skipped
entirely; backticking a word lets you name it). Exit 1 lists every
finding with its line. **A pass is not a review** — whether the downsides are
actually stated is a judgment the checker cannot make, so re-read the draft for
that yourself.

## 2. Stacked PRs — GitHub detects the pattern, no tool required

Do **not** reach for a special stacking tool. GitHub recognizes a stack on its own
whenever all three of these hold:

1. at least two open PRs in the same repository;
2. the bottom PR targets `main` (or another trunk);
3. each next PR's base branch **exactly equals** the previous PR's head branch.

When it sees that pattern it offers to convert the chain into a stack. So the
whole technique is one flag:

```bash
gh pr create --base main            --head feat/01-parser   --title '...' --body-file local/pr-1.md
gh pr create --base feat/01-parser  --head feat/02-renderer --title '...' --body-file local/pr-2.md
gh pr create --base feat/02-renderer --head feat/03-cli     --title '...' --body-file local/pr-3.md
```

**When to split at all.** A long task with several separable concerns, where each
piece is one reviewable idea and the lower piece makes sense on its own. If a
reviewer cannot approve the bottom PR without reading the top one, it is one PR,
not a stack. Note that `CONTRIBUTING.md` asks *outside contributors* to avoid
stacks and to state ordering in the descriptions instead; stacking is for
branches you own in this repo.

**Name branches so the order is legible.** A numeric segment does it:
`feat/01-parser`, `feat/02-renderer`, `feat/03-cli`. The number is for humans
scanning `gh pr list`; nothing reads it.

**Merge order is bottom-up.** Merge the PR that targets `main` first, deleting its
head branch on merge; GitHub then re-targets the next PR's base to `main`
automatically. Merging out of order strands the content of the PRs below. Every
update this causes rewrites SHAs, which orphans the review-ledger rows written on
those branches — see "A stacked PR's row does not survive the merge" below.

**Rebasing the whole stack when the bottom changes.** The trap: a plain
`git rebase <new-base>` replays every commit not already in the new base *by
SHA*. After the bottom PR is squash- or rebase-merged, its changes exist on `main`
under **different SHAs**, so git replays them a second time and each one conflicts
with itself. The correct form names the old base tip explicitly, so only the
commits above it are replayed:

```bash
git fetch origin
# One branch at a time, bottom-up. <old-base-tip> = where this branch used to sit.
git rebase --onto origin/main <old-base-tip> feat/02-renderer
git rebase --onto feat/02-renderer <old-tip-of-02> feat/03-cli
```

Record each branch's old tip (`git rev-parse feat/01-parser`) **before** the merge
that deletes it, or recover it from `git reflog`. Force-push each rebased branch
in the same bottom-up order, and read the guardrail on force-pushing reviewed
branches below.

## 3. Gates, in the order you meet them

Everything here is enforced by tracked hooks (install once with
`.venv/bin/python automation/bootstrap_overlay.py`) plus CI.

| # | Gate | Where | Fails when |
|---|------|-------|-----------|
| 1 | Staged `private/` paths | `automation/hooks/pre-commit` | any `private/` path is staged — `git add -f private/` is silent, this is not |
| 2 | Leak guard over the **staged index** | `automation/publish/check_public.py --staged` | the blob being committed carries identity tokens, structural PII, or an absolute home path |
| 3 | Public review gate | `automation/publish/review_gate.py` | the published tree changed without a row in `automation/publish/review_ledger.yaml` |
| 4 | Vendor drift | `automation/vendoring/sync_vendored.py --check` | a `scripts/_vendor/` copy diverged from `automation/shared/` |
| 5 | Mail send-less policy | `automation/shared/mail/check_mail_safety.py` | any mail path exposes send capability |
| 6 | Byte-compile | `compileall` | a toolkit or skill script has a syntax error |
| 7 | Instruction budget | `automation/metrics/instruction_budget.py --strict` | a `SKILL.md` passes 600 lines, a `LESSONS.md` 160 |
| 8 | Reconciler | `automation/reconcile/reconcile.py --check --require-roots` | a queue/task/memory item breaks its `templates/` schema, the memory index is stale, a session has no handover, `skill-manifests` drifted |
| 9 | Leak guard, armed | `automation/hooks/pre-push` | the guard is UNARMED (no identity tokens) — it refuses the push rather than certify a tree it cannot inspect |

CI re-runs the leak guard and the review gate on the branch tip, plus the unit
suites. A PR that also edits `skills/*/SKILL.md`, `LESSONS.md`, or `reference.md`
must carry canary results or the line `Eval gate: skipped — <intention + size>`
in its body (`evals/README.md`).

### The review gate and the one-commit lag

Every commit that changes the public tree needs a row in
`automation/publish/review_ledger.yaml`. The gate reads **HEAD** (the previous
commit) and the **working-tree** ledger, so a row always acknowledges the commit
before it — one row per commit, always one behind. Concretely:

1. Make change A. The gate passes (it is judging the commit before A). Commit A.
2. Make change B. The gate now fails on A and **prints the exact row**, filled in.
   Read A's diff, then stage that row alongside B and commit once.
3. At the end of the branch there is one unacknowledged commit left. Close it with
   a **ledger-only commit** — it changes no watched file, so it acknowledges the
   tip without creating new work.
4. Only then push. **CI evaluates the tip**, so a branch pushed without the
   closing ledger commit lands red.

The ledger is **append-only**: every row's `digest` is recomputed from the range
it claims, so rewriting a row is itself detected. A row is written after reading
the diff — the digest forecloses guessing, it does not prove reading.

### A stacked PR's row does not survive the merge

A row names a **branch tip**, and updating a stacked PR onto its newly merged base
**rebases it — every commit gets a new SHA**. So a row acknowledged before the
merge names a commit that never lands on `main`. The review was real; the commit
is not in the trunk's history.

The gate handles this rather than jamming: it builds the chain from the rows whose
commit **is** an ancestor of HEAD, skips the orphans, and reports them by name
(`EXISTS here but is NOT an ancestor` when the commit is still in your object
store, `UNKNOWN OBJECT` when it is not — a fresh CI clone carries only reachable
objects, so a deleted branch's commits are simply gone there).

**After merging a stack, on the trunk:**

1. `git checkout main && git pull` — then run the gate. It prints the orphaned rows
   and computes the range from the **closest surviving ancestor row**.
2. **Never edit or delete the orphaned rows.** Append a reconciliation row for the
   trunk tip using the range the gate prints, whose `finding:` says the content was
   already reviewed on the branches and names the twins that landed.
3. Commit it (ledger-only), push, and CI goes green — the recovery uses no orphaned
   commit as a base, so it works in a clone that does not have them.

### The PR body and commit messages are public text

They are written into this public repo's history and its GitHub page, and they are
**not** covered by the staged-index leak guard once they leave your machine.
Three mistakes the leak guard has caught exactly:

- **naming a company from the owner's private tree** — company names are not
  identity tokens, so this one is caught by the review gate's read, not the token
  scan; write `<company>`;
- **quoting a private file** — a recruiter email, an application note, a private
  design doc. Describe the shape, quote nothing;
- **pasting terminal output containing an absolute home path** — `/Users/<name>/…`
  in a verification transcript. Redact to `<repo-root>` before committing.

### Commit-message trailers

Every commit made by an agent in this repo ends with:

```
Co-Authored-By: <model name> <noreply@anthropic.com>
Claude-Session: <session url>
```

Subject line: imperative, ≤72 chars, saying *what* changed; body says *why*
(`CONTRIBUTING.md`). A ledger-only commit says so in its body — "Ledger-only
commit; changes no watched file."

### Never `--no-verify`

`AGENTS.md` forbids it outright, for commit and push alike. The gates above are
the repo's only defense against publishing personal data, and the one failure
they prevent is irreversible: once a blob is in a commit it is in the history.
Fix the finding, or let `reconcile.py --file-retries` queue it. Never weaken a
check to make a commit pass.

## 4. `gh` recipes

| Task | Command |
|------|---------|
| Create a PR with an explicit base | `gh pr create --base <prev-branch> --head <this-branch> --title '<t>' --body-file <path>` |
| List open PRs with base/head | `gh pr list --state open --json number,title,baseRefName,headRefName` |
| CI status for a PR | `gh pr checks <n>` (add `--watch` to block until it settles) |
| Find the failing run | `gh run list --branch <branch> --limit 5` |
| Read a failing run's log | `gh run view <id> --log-failed` |
| Merge state | `gh pr view <n> --json state,mergeable,mergeStateStatus,baseRefName` |
| Merge the bottom of a stack | `gh pr merge <n> --squash --delete-branch` |
| Retarget a PR | `gh pr edit <n> --base main` |

**`gh pr list` and `gh pr view` disagree with reality in a useful way.** Both keep
reporting `baseRefName: feat/01-parser` after that PR merged and its branch was
deleted — they report the stored ref, not a live branch. The disagreement surfaces
at creation time: `gh pr create --base feat/01-parser` fails with
`Base ref must be a branch`. That error means the base merged, not that you typed
it wrong. Fix it by rebasing onto `main` with `--onto` (above) and retargeting
with `gh pr edit <n> --base main`.

## Guardrails (inviolable)

- **Never `--no-verify`**, and never bypass or weaken a gate to make a commit
  land (`AGENTS.md`).
- **Never force-push a branch someone has reviewed without saying so** — comment
  on the PR with what changed and why the history moved, before or immediately
  after the push. A silent force-push destroys the review's line anchors.
- **Never merge your own stack out of order.** Bottom-up, one at a time,
  confirming each merge before the next.
- **A PR whose CI is red is not ready, regardless of local results.** Do not ask
  for a merge, and do not explain the red away.
- **Verify in a config-less checkout before claiming CI will pass.** A detached
  worktree in the gitignored scratch tree reproduces CI's environment — no
  `config.yaml`, no `private/` overlay, no token secret. This has caught three
  real CI failures that passed locally:

  ```bash
  git worktree add --detach local/ci_check HEAD
  # Run the checks against local/ci_check with the primary checkout's venv, then:
  git worktree remove local/ci_check
  ```

- **The PR body and commit messages are public.** No company from the private
  tree, no quoted private file, no absolute home path (see above).
- **Never delete owner data** to make a gate pass — propose it in
  `message-queue/needs-human/` and stop.

## Files

| Path | Purpose |
|------|---------|
| `skills/github-workflow/SKILL.md` | This router — format, stacking, gates, `gh` recipes |
| `skills/github-workflow/scripts/check_pr_body.py` | Validates a PR body against the human-facing format (file or stdin; exit 1 with findings) |
| `skills/github-workflow/scripts/tests/` | `unittest` suite for the checker |
| `evals/canaries/github-workflow.yaml` | Canary set for this skill (`evals/README.md`) |
| `.github/pull_request_template.md` | The checklist half of a PR body; the human-facing section goes above it |
| `automation/publish/review_ledger.yaml` | The append-only review record the review gate reads |
| `CONTRIBUTING.md` | Contributor-facing rules: branch naming, the check list, the eval gate |
