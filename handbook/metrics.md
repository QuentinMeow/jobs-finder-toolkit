# Optional metrics collection (opt-in)

The toolkit ships a tiny, zero-platform metrics collector
(`automation/metrics/hook_collect.py`) that appends one JSON line per event to a
git-ignored `logs/metrics.jsonl`. It is **opt-in and local only**: nothing is
tracked and no hook runs unless *you* wire it up. This keeps clones and CI clean
— a tracked `.claude/settings.json` would run the hooks in every checkout and
error wherever `.venv/` is absent.

## What it collects

Wired to three Claude Code hooks, all writing to `logs/metrics.jsonl`:

- **SessionStart** — `{ts, event, session_id, model, source, git_sha}`
- **PostToolUse** — `{ts, event, session_id, tool_name}`
- **Stop** — `{ts, event, session_id, <token sums>, wall_clock_s, tool_calls, transcript_lines}`

The collector is fail-safe: it always exits 0 and never blocks a session. See
`automation/metrics/report.py` for a summary report over the log.

## How to enable it

Add the `hooks` block below to your **`.claude/settings.local.json`** (which is
git-ignored — see `.gitignore`). Merge it alongside any existing `permissions`
block; do not create a tracked `.claude/settings.json`.

```json
{
  "hooks": {
    "SessionStart": [
      {
        "matcher": "startup|resume|clear|compact",
        "hooks": [
          {
            "type": "command",
            "command": "${CLAUDE_PROJECT_DIR}/.venv/bin/python ${CLAUDE_PROJECT_DIR}/automation/metrics/hook_collect.py session-start",
            "timeout": 10
          }
        ]
      }
    ],
    "PostToolUse": [
      {
        "matcher": "*",
        "hooks": [
          {
            "type": "command",
            "command": "${CLAUDE_PROJECT_DIR}/.venv/bin/python ${CLAUDE_PROJECT_DIR}/automation/metrics/hook_collect.py post-tool-use",
            "timeout": 5
          }
        ]
      }
    ],
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "${CLAUDE_PROJECT_DIR}/.venv/bin/python ${CLAUDE_PROJECT_DIR}/automation/metrics/hook_collect.py stop",
            "timeout": 15
          }
        ]
      }
    ]
  }
}
```

The hooks call `${CLAUDE_PROJECT_DIR}/.venv/bin/python`, so create the virtualenv
first (`python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`).
Both `logs/` and `.claude/settings.local.json` are git-ignored, so enabling
metrics never dirties the tree.
