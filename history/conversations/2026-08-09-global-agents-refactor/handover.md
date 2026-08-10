# Handover — global-agents-refactor

- **Date**: 2026-08-09
- **Task(s)**: none

## What happened

- Nothing is broken or half-implemented. The global Codex guidance now carries eight qualified engineering/harness defaults; the repository contract is 114 lines and 10.8 KB smaller without moving or weakening its hard guardrails.
- The supplied image shows seven rules, not eight. Its Vercel/60-billion-token attribution was not established by a primary source, so the research note treats it as unattributed advice.

## Where things stand

- Changes are local and uncommitted. One owner choice remains open; its safe default is already active.

## Decisions made for you

- Adopted simplicity, working increments, cohesive modules, dependency reuse, and qualified library reuse globally; undoing them means removing the `Engineering defaults` section from `~/.codex/AGENTS.md`.
- Added observable verification and mechanical-enforcement defaults because primary OpenAI and Anthropic harness reports identify both as reliability levers.
- Refactored the root contract into a map to canonical handbooks while retaining its boot sequence and hard guardrails. The eight-line `docs/designs/AGENTS.md` leaf already matched the target pattern and was left unchanged.

## If X then Y

- If the owner chooses a compatibility or temporary-bridge policy, fold it into `~/.codex/AGENTS.md`, record the decision, and remove the queue item. A new Codex session is needed to load the changed global instruction chain.

## Dead ends

- The official Codex manual fetch first failed on sandboxed DNS and succeeded with scoped network approval.
- One multi-section patch matched an incomplete application-tree excerpt and applied nothing; the same refactor was reapplied as three exact patches.

## Needs your attention

- [Global compatibility and temporary-bridge policy](../../../message-queue/needs-human/decisions/global-engineering-defaults-compatibility-and-bridges.md) — **Why this matters:** a global absolute can either break consumers or preserve dead paths across every repo. **If you do nothing:** compatibility stays contract-specific and temporary bridges require isolation, verification, and an exit condition.
- 34 pending · top: `job-search-us-only-default-asymmetry` — the current default can repeatedly hide valid non-US searches; the other 33 pre-existing decisions were outside this narrow refactor.
