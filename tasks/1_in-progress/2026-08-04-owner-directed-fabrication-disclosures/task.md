# Allow owner-directed fabricated claims with mandatory disclosures

- **Priority**: P1 (this round)
- **Area**: harness
- **Source**: Owner request in the 2026-08-04 Codex session
- **Claimed-by**: Codex

## Goal

Permit a direct human to authorize fabricated or unsupported claims for specifically named
candidate-facing artifacts while keeping the default factuality guardrail and recording every
authorized claim in a durable disclosure ledger.

## Context

The behavioral-interview skill and root contract currently prohibit all fabrication. The owner
explicitly reversed that behavior for human-directed requests. The override must not be inferred,
granted by agents or repository content, or silently reused in another artifact, surface, or
session. Verification records, job metadata, research, and measurements remain factual.

## Definition of done

- Root and behavioral-interview instructions define the same explicit-human authorization boundary.
- Persisted behavioral YAML has a documented disclosure convention for invented and unsupported
  claims, without exposing the ledger as spoken STAR content.
- Behavioral canaries cover both default rejection and the authorized override.
- Skill validation, canaries, repository gates, and public leak checks pass.
