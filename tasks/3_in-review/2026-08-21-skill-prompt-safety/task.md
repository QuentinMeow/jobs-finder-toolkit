# Reduce skill prompt-rejection risk

- **Priority**: P1 (this round)
- **Area**: harness
- **Source**: Owner request on 2026-08-21 after an intermittent Codex invalid-prompt rejection
- **Claimed-by**: Codex

## Goal

Reduce avoidable prompt-safeguard risk in the company-research workflow, add reusable authoring guidance and automated checks, and audit the public and private skill trees without weakening domain behavior.

## Context

Two GPT-5.6 turns were rejected after company-research context had been loaded. The same skill and realistic Salesforce application context later loaded successfully, so no single sentence is a proven policy violation. Treat the incident as an intermittent service-side safeguard event with context shape as a controllable risk factor. Preserve all existing requirements through progressive disclosure and do not expose private skill content in public artifacts.

## Definition of done

- `company-research/SKILL.md` has a lightweight quick path and routes detailed material on demand.
- Skill-creation guidance documents prompt-surface and forward-test safeguards.
- Every public and private `SKILL.md` is included in a static risk audit.
- Fresh GPT-5.6-sol xhigh subagents smoke-test the repaired skill and representative risk-ranked skills.
- Applicable validators, instruction-budget checks, canaries, and repository gates are recorded with real results.
