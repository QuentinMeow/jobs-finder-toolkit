# Add shell-conventions + read-hygiene notes to AGENTS.md

- **Status**: todo
- **Priority**: P1
- **Area**: repo
- **Source**: transcript mining, 2026-07-20 (`tmp/transcript_mining/report.md`) —
  ~5,100 tool calls across 134 threads

## Goal

Two short AGENTS.md conventions that eliminate the two measured, preventable
waste classes in agent transcripts:

1. **Shell conventions**: this repo's shell is zsh — always use absolute paths
   (subagent cwd resets between calls broke 30 commands via bare relative
   `cd`); quote `=`-leading and glob-bearing arguments (5 `echo ===`
   equals-expansion failures, 2 NOMATCH glob failures).
2. **Read hygiene**: never re-Read a file unchanged since the last Read
   (94 within-thread duplicate reads ≈ 103k tokens, fully avoidable); for
   files >800 lines, prefer grep/offset-slice reads over full-file reads
   (~204k tokens of full reads where a slice would do).

## Context

Transcript mining of the 2026-07-19/20 sessions showed genuine tool failures
are rare (0.67%) and meaningless retries near-zero (2 total) — the measured
waste is context ingestion and a small preventable Bash-failure class. These
two notes are the cheapest structural fix. Keep them to ~4 lines total
(AGENTS.md line budget: 500; check `instruction_budget.py --strict`).

## Definition of done

- AGENTS.md carries both conventions (Conventions section or Handy Commands
  preamble), within budget.
- Re-running the miner (`tmp/transcript_mining/analyze.py`) over sessions
  after the change shows duplicate-read count and the relative-path/zsh
  failure class trending to ~zero.
