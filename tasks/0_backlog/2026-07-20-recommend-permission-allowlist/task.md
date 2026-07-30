# Recommend a Claude Code permission allowlist for this repo (owner applies)

- **Priority**: P2
- **Area**: repo
- **Source**: transcript mining, 2026-07-20 (`local/transcript_mining/report.md`)

## Goal

Stop the measured permission-classifier friction: in the mined sessions the
auto-mode classifier hard-blocked git-history operations (`git branch -f`,
`git push`, `git worktree add`, `--no-verify`) and subagent spawns 9+ times,
each block costing a stalled turn and rework tokens.

## Context

Permissions are the owner's security posture, so agents must not edit
`.claude/settings.local.json` themselves — this task is a recommendation the
owner applies (the `/fewer-permission-prompts` skill can also generate one
from transcripts). The repo deliberately has no tracked `.claude/settings.json`
(see docs/handbook/metrics.md rationale). Suggested starting allowlist, merged into the
existing `permissions.allow` block (which already has `Bash(git *)`):

```json
{
  "permissions": {
    "allow": [
      "Bash(git *)",
      "Bash(gh *)",
      "Task",
      "Bash(.venv/bin/python *)",
      "Bash(/Users/<owner>/code/<repo>/.venv/bin/python *)"
    ]
  }
}
```

(Replace the absolute-path entry with the real checkout path; drop any row
the owner is uncomfortable auto-allowing — `git push` in particular.)

## Definition of done

- Owner has applied (or explicitly declined) an allowlist; a later mining
  run shows permission-denial blocks at ~zero.

## 2026-07-29 — the Source line cites gitignored scratch

This task's **Source** points at `local/transcript_mining/report.md` (the path was
`tmp/transcript_mining/report.md` when it was written; workspace phase 2 renamed the scratch
root). That is a durable record citing gitignored scratch as its evidence — the exact
anti-pattern the scratch section of
[`docs/handbook/file-organization.md`](../../../docs/handbook/file-organization.md#scratch--temporary-files)
has forbidden since phase 1: a record that cites scratch is evidence with an expiry date and no
expiry signal. Nobody but this checkout can verify the "9+ hard-blocks" measurement above, and
the scratch tree is exactly the tree the owner has an open review item about clearing.

**Before this task is actioned**, replace the citation with the evidence itself — the mined
counts, and enough of the blocking commands to justify each allowlist row — pasted inline. The
citation stays until then rather than being deleted, because it is still the only pointer to
where the numbers came from.

