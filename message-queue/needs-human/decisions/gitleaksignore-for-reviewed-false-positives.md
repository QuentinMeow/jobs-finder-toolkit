# Should this repo carry a `.gitleaksignore` for reviewed false positives?

- **Status**: awaiting-owner-input
- **Filed**: 2026-07-31
- **Source**: [PR 07 verification](../../../tasks/3_in-review/2026-07-31-company-index-validators-disagree/verification.md)
- **Blocks**: nothing — PR #128 is green on the default path below
- **Default path**: a `.gitleaksignore` exists at the repo root with exactly two
  commit-pinned fingerprints and a header stating the rule for adding a third. Agents add an
  entry only after reading the flagged line and confirming it is not a credential.
- **Cost if wrong**: ratify
- **Safe to merge because**: the file holds exactly two reviewed entries; deleting it re-arms
  gitleaks in one commit, and no unreviewed finding is suppressed.

## Background

CI's `secret-scan` job runs `gitleaks/gitleaks-action@v2` with no config, so it uses gitleaks'
default ruleset. Its `generic-api-key` rule matches, roughly, *an identifier containing
`key`/`token`/`secret`/`auth`, then a separator, then a quoted 10+ character value*.

A unit test in this repo builds throwaway application folders whose names are invented slugs.
One line put two of them side by side, and the first contained the substring `key` — so the rule
read the second slug as the secret. Nothing in it is a credential; every value is a folder name
written into a `tempfile` directory and deleted at the end of the test.

The current file no longer has the shape (both slugs were renamed). But the job fires twice per
push with different scopes:

- the **push** run scans only the newly pushed commits — green once the shape is gone;
- the **pull_request** run scans the whole PR range — still red, because two earlier commits'
  DIFFS contain the line, and a diff cannot be edited without rewriting published history.

Rewriting is not available here: the review ledger pins each commit's sha and digest, and
`skills/github-workflow/SKILL.md` records that rebasing a stacked branch orphans its rows.

## Options

### Option A — a root `.gitleaksignore` with commit-pinned fingerprints (the default path)
One line per reviewed finding, `<commit>:<file>:<rule>:<line>`. Gitleaks reads it automatically;
the ruleset is untouched, so the same shape anywhere else — including the same file on a later
line — still fires. Structurally the same promise as `automation/publish/review_ledger.yaml`: a
fingerprint names one diff a human read. Cost: a new root file, and a place where an entry could
one day be added carelessly. The header states the rule for adding one.

### Option B — a `.gitleaks.toml` that narrows or disables `generic-api-key`
Fixes the class rather than the instance. Much blunter: `generic-api-key` is the rule most likely
to catch a real pasted credential, and narrowing it repo-wide to silence two test fixtures trades
a real gate for a cosmetic one. Not recommended.

### Option C — accept a permanently red `pull_request` secret-scan on this PR
Honest, and costs nothing structurally. But a check that is expected to be red is a check nobody
reads, and this stack has six other PRs whose green status is the signal. Not recommended.

### Option D — rewrite the branch history so the diffs never contained the line
Would make the finding genuinely disappear. Forbidden here: it orphans the review-ledger rows
written for this branch, which is exactly the failure the ledger's append-only rule exists to
prevent.

## Recommendation

**Option A.** The finding is real pattern-matching on text that is genuinely not a secret, and
the narrowest honest response is to record that judgement against those two specific diffs rather
than to change what the scanner looks for. It also gives the repo a place to record the next one,
with a stated bar for entry — which is better than the current situation, where the only options
are "rewrite history" or "live with red".

If you would rather not carry the file at all, Option C is the fallback and the two entries can
be deleted; nothing else in the repo depends on them.

**Your answer:** ______
