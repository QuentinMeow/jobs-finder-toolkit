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

## Phase recorder (Codex-compatible, opt-in)

The hook collector above only works where a harness fires hooks and writes a
transcript. The **phase recorder** is the harness-agnostic alternative: a plain
CLI any agent (Codex, Claude Code, a human shell) calls to bracket its own work,
so a session's wall clock can be split into named phases afterwards.

- `automation/metrics/phase_recorder.py` — writer. Appends one JSON line per
  event to `logs/phases/<session>.jsonl`.
- `automation/metrics/phase_summary.py` — reader. Computes the time accounting
  and emits a **redacted** summary (JSON, a paste-ready markdown table, or a
  plain table).

`logs/` is both git-ignored and on the leak guard's path denylist, so raw phase
events are structurally uncommittable. Neither tool is a gate: they are absent
from `automation/gates/run_gates.py`, CI, and the pre-commit hook on purpose — a
telemetry threshold that blocks a commit turns an honesty tool into something
people work around.

### The four numbers, kept separate

The summary never rolls these into one figure, because two of them can describe
the same second and collapsing them would make one of them wrong.

| number | how it is obtained | what it means |
|---|---|---|
| `local_subprocess` | **measured** — the wrapper's own clock around each `run` child | the only category with hard ground truth |
| `external_wait` | **declared** — a `run --kind external`, or the remainder of an `external_wait`-kind phase | waiting on somebody else's machine (CI, a review, a fetch) |
| `approval_wait` | **declared** — paired `mark approval-start` / `approval-end`, or an `approval`-kind phase | a human or sandbox gate holding the agent |
| `active` | **residual** — everything left inside a named phase | model reasoning, streaming, tool-result handling and short human turns, undifferentiated |

`active` is a residual, not a measurement. Calling it "reasoning time" would be
a fabrication: nothing in it is separately observed.

Beside them sits `wrapped_subprocess_s`, an **overlay** rather than a partition
member: it sums every `run` child regardless of class. `gh pr checks --watch` is
simultaneously a wrapped subprocess and a GitHub wait, so the summary states the
overlap (`wrapped_local_s` + `wrapped_external_s`) instead of picking one.

Everything else is `unattributed`, itemised by name — `pre_arm`,
`between_phases`, `long_gap`, `clock_skew`, `after_last_event`. A silence longer
than `--idle-threshold` (default 120 s) inside a phase becomes `long_gap`, not
`active`: six quiet minutes are not evidence of six minutes of reasoning. Early
runs will report embarrassing `long_gap` and `pre_arm` numbers, and that is
correct — the failure mode to guard against is a later "improvement" that
reclassifies them into `active` to make coverage look better.

The five classes partition the reference total exactly. Because `active` is the
residual, double-counted time surfaces as a negative, which is clamped to 0,
flagged as `integrity.accounting_error`, and explained in a note — a negative is
never published.

### Coverage always names its denominator

Two percentages are reported side by side and never conflated:

- `phase_coverage_pct` — was this second inside a *named phase*;
- `class_attribution_pct` — do we know what *kind* of second it was.

Both divide by `reference_total_s`, and `reference_source` says which
denominator that is:

- `external_supplied` — a total the operator read off the harness UI and passed
  to `session end --external-total-s`. Only this makes coverage a real claim,
  and only this yields `pre_arm_s`, the head time before the recorder was armed;
- `recorder_span_s` — the recorder's own first-to-last event span. With
  contiguous `set`, coverage against it is ~100% **by construction** and proves
  nothing. The summary prints a note saying so.

A coverage number quoted without its denominator is meaningless. Quote the
footer line, which carries both.

### Usage

Nothing is enabled by default; the recorder only runs when an agent calls it.

```bash
PY=.venv/bin/python
REC=automation/metrics/phase_recorder.py

# Arm the session (prints the id; also written to logs/phases/current.json).
SESSION=$($PY $REC session start --label recon --harness codex --repo-role public)

# Name what you are doing. `set` is the default: it closes the previous phase and
# opens the next at ONE instant, so the timeline has no holes.
$PY $REC set inventory
$PY $REC set mutation

# Wrap a command: it is timed, its exit code is recorded, and the recorder
# returns THAT exit code verbatim. Streams are inherited, never piped.
$PY $REC run --phase validation -- $PY automation/gates/run_gates.py

# A wait on somebody else's machine is declared, not guessed.
$PY $REC run --kind external -- gh pr checks --watch

# An approval pause is declared with a pair of marks, or not counted at all.
$PY $REC mark approval-start
$PY $REC mark approval-end

$PY $REC status                     # after a compaction: what session/phase am I in?
$PY $REC session end --external-total-s 1653

# Read it back.
$PY automation/metrics/phase_summary.py --last --markdown
```

Phase names: `inventory`, `context`, `plan`, `mutation`, `validation`, `commit`,
`publish`, `external_wait`, `closeout`. An unknown name is **accepted** and
recorded (rejecting it would tempt an agent to skip instrumenting at all); the
summary collapses it to `other` plus a digest.

Useful flags on the summary: `--json`, `--out PATH`, `--idle-threshold SECONDS`,
`--strict` (exit 1 on a redaction self-check hit), `--min-coverage PCT` (exit 1
below the threshold — a manual verification-record aid, **never** a gate), and
`--unredacted` (diagnostics; requires `--out` and refuses any path that is not
under `logs/` or `local/`).

Every subcommand exits 0 even when the log directory is unwritable, the pointer
file is missing, or the log is corrupt — telemetry must never break a session.
The single exception is `run`, which returns the child's status verbatim,
including when recording failed entirely: reporting a failed command as green
would break a hard guardrail.

### Redaction

The summary schema is **structurally** redacted: every field is a number, a
duration, or a value from a closed enum, so there is no free-text field for a
path, branch, label, command line or repository name to survive in. That is
stronger than scrubbing free text with a filter, which fails open on any leak
shape it does not recognise. Raw session ids become `session_digest`,
repositories become `role` + `fingerprint`, commands collapse to an allowlisted
`cmd_head` (`git|gh|python|soffice|other`), and notes are built from a fixed
catalogue with numeric fields only. The leak guard's own scan runs over the
rendered output as belt and braces, not as the primary mechanism.

One honest caveat: a digest is a **fingerprint, not encryption**. It is one-way,
but a short, low-entropy input (a session label, a phase name) could be
*confirmed* by somebody who already guessed it. Its job is to tell two things
apart without naming either, not to keep a secret.

### What this cannot measure

Stated plainly, because a tool that quietly guessed here would produce exactly
the invented attribution the repository forbids.

1. **Approval wait, in general.** The approval prompt happens *between* two
   recorder invocations, and in a fully-gated sandbox the recorder's own first
   call is itself awaiting approval. Where no marks exist, `approval_wait_s` is
   `0.0` and that zero means *not measured*, not *there was none*; the summary
   says so in a note whenever it is zero and any `long_gap` exists.
2. **The composition of `active_s`.** Reasoning, streaming, tool-result handling
   and a short human turn are one undifferentiated bucket. No CLI invoked from a
   shell can separate them.
3. **Time before `session start` and after `session end`.** Recoverable only if
   a human reads the harness UI and passes `--external-total-s`. Without it the
   largest interval of a session — the head containing context loading — is
   simply outside the recorder's span, and the summary says
   `reference_source: recorder_span` rather than imply completeness.
4. **Token counts, for harnesses that expose no usage to a child process.** The
   summary emits the literal string `not_measured`, never an estimate.
5. **Unwrapped tool calls.** File reads, edits, greps and any command run without
   `run` are invisible; their time falls into `active_s`. The field is named
   `wrapped_commands` and `tool_calls` is `not_measured`, because calling wrapped
   commands "tool calls" would understate real tool volume by a large and
   unknown factor.
6. **CI queue time vs CI execution time.** A watch command measures their sum;
   splitting them needs per-check timings from the forge API. Reported as one
   `external_wait` number.
7. **Why a `long_gap` happened.** An approval prompt, a human away, and a slow
   model turn are indistinguishable from outside. Reported by count and seconds,
   classified never.
8. **Whether the agent instrumented itself honestly.** Every phase nobody
   brackets becomes `between_phases`. The tool measures discipline as much as
   the agent, and it cannot fix that.
