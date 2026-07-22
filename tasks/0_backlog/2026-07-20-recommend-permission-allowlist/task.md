# Recommend a Claude Code permission allowlist for this repo (owner applies)

- **Priority**: P2
- **Area**: repo
- **Source**: transcript mining, 2026-07-20 (`tmp/transcript_mining/report.md`)

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
(see handbook/metrics.md rationale). Suggested starting allowlist, merged into the
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
